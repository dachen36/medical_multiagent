"""整改方案 §B1' / §B7 / §B6 — 临床工作流 + 会话状态 + 意图分类

设计要点（基于和用户的对话确认）：
  1. "4 阶段"是默认模板，不是写死剧本。每个阶段是"可寻址单元"，
     用户（通过意图分类器）或系统（通过路由规则）可独立调用任意子集。
  2. 第 2 轮起的追问不需要走完整 4 阶段，只跑相关子集（例如"退烧药选什么"
     只跑 analysis，"补充知识"只跑 knowledge）。
  3. 意图分类器 S2 用 rule-based 实现（关键词 + 轮次 + 已有病历状态），
     后续可替换为轻量 LLM。
  4. 会话状态机持久化在内存 dict（按 session_id 隔离），跨 /ws/scenario
     调用累积；首次触发走"问诊采集"扩出 patient_record，后续轮次复用。
"""
from __future__ import annotations

import asyncio
import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional


# ---------------------------------------------------------------------------
# §B1': Stage 契约（数据类）
# ---------------------------------------------------------------------------
# 每个 stage 是一个"可寻址的执行单元"，有明确的：
#   - name: 标识
#   - agents: 要调用的智能体列表（1 或多个）
#   - parallel: 多个 agent 是否并行（True=asyncio.gather, False=await 顺序）
#   - input_keys: 需要的 ctx 中的 key
#   - output_keys: 写入 ctx 的 key
#   - depends_on: 哪些 stage 必须在它之前完成
#   - block_on_red_flag: intake stage 命中红旗后是否立即终止后续 stage
#   - description: 给 LLM/前端看的描述
# ---------------------------------------------------------------------------
@dataclass
class StageContract:
    name: str
    label: str
    agents: list[str]
    parallel: bool
    input_keys: list[str]
    output_keys: list[str]
    depends_on: list[str] = field(default_factory=list)
    block_on_red_flag: bool = False
    description: str = ""


# 内置 5 个 stage 的契约
INTAKE_STAGE = StageContract(
    name="intake",
    label="问诊采集",
    agents=["intake-specialist"],
    parallel=False,
    input_keys=["user_request", "intake_qa"],
    output_keys=["patient_record", "red_flag", "interview_done"],
    block_on_red_flag=True,
    description="9 段式问诊、病历 CRUD、OCR、实体抽取。命中红旗立即终止。",
)

KNOWLEDGE_STAGE = StageContract(
    name="knowledge",
    label="知识检索",
    agents=["knowledge-specialist"],
    parallel=False,
    input_keys=["user_request", "patient_record", "entities"],
    output_keys=["evidence", "blind_spots", "kg_hits"],
    depends_on=[],
    description="TOC + RAG + KG 三引擎混合搜索；盲区自动发现。",
)

ANALYSIS_STAGE = StageContract(
    name="analysis",
    label="智能分析",
    agents=["analysis-specialist"],
    parallel=False,
    input_keys=["user_request", "patient_record", "entities", "evidence"],
    output_keys=["drug_check", "lab_interp", "ddx", "bias_check"],
    depends_on=[],
    description="药物互作 / 化验解读 / 5 维度鉴别诊断 / 认知偏差自检。",
)

# 知识+分析 是真正的并行 stage
KNOWLEDGE_ANALYSIS_PARALLEL = StageContract(
    name="knowledge_analysis",
    label="知识+分析",
    agents=["knowledge-specialist", "analysis-specialist"],
    parallel=True,
    input_keys=["user_request", "patient_record", "entities"],
    output_keys=["evidence", "drug_check", "lab_interp", "ddx"],
    depends_on=[],
    description="知识检索 + 智能分析 并行执行。",
)

EVOLUTION_STAGE = StageContract(
    name="evolution",
    label="自我进化",
    agents=["evolution-specialist"],
    parallel=False,
    input_keys=["patient_record", "ddx", "drug_check"],
    output_keys=["pattern_hits", "kg_injections", "evolution_state"],
    depends_on=["knowledge_analysis"],  # 等待知识+分析完成
    description="从本次问诊提取诊断模式 → 提炼规律 → 注入 KG。",
)

REPORT_STAGE = StageContract(
    name="report",
    label="综合报告",
    agents=["team-coordinator"],
    parallel=False,
    input_keys=["*"],  # 综合全部输入
    output_keys=["final_report", "self_assessment"],
    depends_on=["intake", "knowledge_analysis", "evolution"],
    description="协调者综合所有 specialist 输出 + 撰写系统自评。",
)


# 内置 stage 注册表
STAGE_REGISTRY: dict[str, StageContract] = {
    "intake": INTAKE_STAGE,
    "knowledge": KNOWLEDGE_STAGE,
    "analysis": ANALYSIS_STAGE,
    "knowledge_analysis": KNOWLEDGE_ANALYSIS_PARALLEL,
    "evolution": EVOLUTION_STAGE,
    "report": REPORT_STAGE,
}


# ---------------------------------------------------------------------------
# §B6: 默认完整工作流模板
# ---------------------------------------------------------------------------
# 第 1 轮 (无 patient_record) → 全 4 阶段
# 第 2 轮起 → 走意图分类器选 stage
DEFAULT_FULL_WORKFLOW: list[str] = [
    "intake",
    "knowledge_analysis",  # 并行
    "evolution",
    "report",
]


# ---------------------------------------------------------------------------
# §B6: 意图分类（rule-based）
# ---------------------------------------------------------------------------
class Intent(str, enum.Enum):
    NEW_CASE = "new_case"             # 新病例 → 走 full
    FOLLOW_UP_DRUG = "follow_up_drug"     # 用药复查 → analysis
    FOLLOW_UP_KNOWLEDGE = "follow_up_knowledge"  # 知识补充 → knowledge
    FOLLOW_UP_DIAG = "follow_up_diag"     # 重新评估 → knowledge + analysis
    META_QUERY = "meta_query"         # 系统查询 → evolution
    UNKNOWN = "unknown"               # 默认 → full（保守）


# 关键词 → 意图的映射
_INTENT_RULES: list[tuple[Intent, list[str]]] = [
    (Intent.FOLLOW_UP_DRUG, [
        "药", "用药", "服药", "剂量", "退烧", "止痛", "抗生素", "处方", "药名",
        "药物", "副作用", "相互作用", "禁忌", "怎么吃", "能吃", "能不能",
    ]),
    (Intent.FOLLOW_UP_KNOWLEDGE, [
        "原理", "机制", "什么是", "什么叫", "解释", "教材", "指南", "文献",
        "为什么", "知识", "科普",
    ]),
    (Intent.FOLLOW_UP_DIAG, [
        "复查", "复诊", "重新", "再评估", "重新判断", "重新考虑", "是...还是",
        "严不严重", "什么病", "诊断", "是不是", "可能", "排除",
    ]),
    (Intent.META_QUERY, [
        "学到了", "进化", "记忆", "模式", "统计", "系统", "MetaClaw",
        "你是什么", "团队", "能力",
    ]),
]


def classify_intent(
    user_request: str,
    has_patient_record: bool,
    round_no: int,
) -> Intent:
    """Rule-based intent classifier.

    Args:
        user_request: 用户输入
        has_patient_record: 当前会话是否已有 patient_record
        round_no: 当前是第几轮（1 = 首次）

    Returns:
        Intent. 第 1 轮总是 NEW_CASE；后续轮按关键词匹配。
    """
    if round_no <= 1 or not has_patient_record:
        return Intent.NEW_CASE

    text = user_request.lower()
    # 按规则优先级匹配（前面的更具体）
    for intent, keywords in _INTENT_RULES:
        for kw in keywords:
            if kw in text:
                return intent
    return Intent.UNKNOWN


def stages_for_intent(intent: Intent) -> list[str]:
    """根据意图返回要执行的 stage 列表。"""
    match intent:
        case Intent.NEW_CASE:
            return DEFAULT_FULL_WORKFLOW
        case Intent.FOLLOW_UP_DRUG:
            return ["analysis"]
        case Intent.FOLLOW_UP_KNOWLEDGE:
            return ["knowledge"]
        case Intent.FOLLOW_UP_DIAG:
            return ["knowledge_analysis", "report"]  # 重新分析 + 增量报告
        case Intent.META_QUERY:
            return ["evolution"]  # 进化 specialist 自报当前状态
        case Intent.UNKNOWN:
            # 保守：跑 analysis + report（不重做 intake）
            return ["analysis", "report"]


# ---------------------------------------------------------------------------
# §B7: 会话状态
# ---------------------------------------------------------------------------
@dataclass
class SessionState:
    """Per-session workflow state.

    S2 阶段：内存 dict，进程重启后清空；S4 阶段可换 SQLite。
    """
    session_id: str
    round_no: int = 0
    completed_stages: list[str] = field(default_factory=list)
    # ctx: stage 间共享的数据（intake_qa, patient_record, evidence, ddx...）
    ctx: dict[str, Any] = field(default_factory=dict)
    last_intent: Optional[Intent] = None
    last_stages: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()


# 进程内会话注册表；key = session_id
_SESSION_STORE: dict[str, SessionState] = {}


def get_or_create_session(session_id: Optional[str] = None) -> SessionState:
    if session_id and session_id in _SESSION_STORE:
        return _SESSION_STORE[session_id]
    sid = session_id or f"ses_{uuid.uuid4().hex[:12]}"
    s = SessionState(session_id=sid)
    _SESSION_STORE[sid] = s
    return s


def list_sessions() -> list[SessionState]:
    return list(_SESSION_STORE.values())


def reset_session(session_id: str) -> bool:
    return _SESSION_STORE.pop(session_id, None) is not None


# ---------------------------------------------------------------------------
# §B3: WorkflowScheduler
# ---------------------------------------------------------------------------
# 一个 stage 的执行器签名：
#     async def executor(ctx, cancel, session, queue) -> dict[output_key, value]
# 执行器在执行过程中把 agent.* 流式事件 put 到 queue（让 UI 实时看到），
# 完成后返回 outputs dict（写入 ctx）。
# ---------------------------------------------------------------------------
StageExecutor = Callable[
    [dict, asyncio.Event, "SessionState", asyncio.Queue],
    Awaitable[dict],
]


class WorkflowScheduler:
    """按 stage 契约调度执行链。

    用法：
        sched = WorkflowScheduler(executors={
            "intake": intake_executor,
            "knowledge_analysis": ka_executor,
            ...
        })
        async for ev in sched.run(stages=[...], ctx={...}, session=s, cancel=c):
            yield ev  # scenario.start / stage.start / agent.* / stage.done / ...
    """

    def __init__(self, executors: dict[str, StageExecutor]) -> None:
        self.executors = executors

    async def run(
        self,
        stages: list[str],
        ctx: dict,
        session: SessionState,
        cancel: asyncio.Event,
        bypass_dep_check: bool = False,  # S5-E — incremental 模式跳过 depends_on 检查
    ) -> AsyncIterator[dict]:
        """Run a list of stage names in declared order, honoring depends_on."""
        # 共享 queue：executor 把 agent.* 事件 put 进来，
        # scheduler 在两次 stage 之间（也包括 stage 内）drain 它。
        stream_queue: asyncio.Queue = asyncio.Queue()

        yield {
            "type": "scenario.start",
            "round": session.round_no,
            "stages": stages,
            "ts": time.time(),
        }

        for stage_name in stages:
            if cancel.is_set():
                yield {"type": "scenario.done", "status": "cancelled", "ts": time.time()}
                return

            contract = STAGE_REGISTRY.get(stage_name)
            if contract is None:
                yield {
                    "type": "stage.error",
                    "stage": stage_name,
                    "detail": f"unknown stage: {stage_name}",
                    "ts": time.time(),
                }
                continue

            # Pre-check: depends_on（incremental 模式跳过此检查）
            if not bypass_dep_check:
                missing_dep = next(
                    (dep for dep in contract.depends_on if dep not in session.completed_stages),
                    None,
                )
                if missing_dep is not None:
                    yield {
                        "type": "stage.error",
                        "stage": stage_name,
                        "detail": f"missing dependency: {missing_dep}",
                        "ts": time.time(),
                    }
                    yield {
                        "type": "scenario.done",
                        "status": "error",
                        "detail": f"stage {stage_name} requires {missing_dep}",
                        "ts": time.time(),
                    }
                    return

            # 阶段开始事件
            yield {
                "type": "stage.start",
                "stage": stage_name,
                "label": contract.label,
                "mode": "parallel" if contract.parallel else "serial",
                "agents": contract.agents,
                "ts": time.time(),
            }

            executor = self.executors.get(stage_name)
            if executor is None:
                yield {
                    "type": "stage.error",
                    "stage": stage_name,
                    "detail": f"no executor registered for stage: {stage_name}",
                    "ts": time.time(),
                }
                yield {
                    "type": "scenario.done",
                    "status": "error",
                    "detail": f"no executor for {stage_name}",
                    "ts": time.time(),
                }
                return

            # 启动 executor 任务（它会异步把事件 put 到 stream_queue）
            executor_task = asyncio.create_task(
                executor(ctx, cancel, session, stream_queue)
            )

            # 在 executor 跑完之前，drain queue 里的 agent.* 事件给上层
            outputs: dict = {}
            executor_failed: Optional[BaseException] = None
            while not executor_task.done():
                # 等 50ms 看有没有新事件
                try:
                    ev = await asyncio.wait_for(stream_queue.get(), timeout=0.05)
                    yield ev
                except asyncio.TimeoutError:
                    pass
                if cancel.is_set() and not executor_task.done():
                    executor_task.cancel()
            # 收尾：drain 剩余事件
            while True:
                try:
                    ev = stream_queue.get_nowait()
                    yield ev
                except asyncio.QueueEmpty:
                    break
            # 等 executor 真正完成（它可能 raise）
            try:
                outputs = await executor_task
            except asyncio.CancelledError:
                executor_failed = asyncio.CancelledError("cancelled")
            except Exception as e:
                executor_failed = e

            if executor_failed is not None:
                if isinstance(executor_failed, asyncio.CancelledError):
                    yield {
                        "type": "stage.error",
                        "stage": stage_name,
                        "detail": "cancelled",
                        "ts": time.time(),
                    }
                    yield {"type": "scenario.done", "status": "cancelled", "ts": time.time()}
                else:
                    yield {
                        "type": "stage.error",
                        "stage": stage_name,
                        "detail": f"{type(executor_failed).__name__}: {executor_failed}",
                        "ts": time.time(),
                    }
                    yield {
                        "type": "scenario.done",
                        "status": "error",
                        "detail": f"stage {stage_name} failed: {executor_failed}",
                        "ts": time.time(),
                    }
                return

            # 写入 session 上下文
            for k, v in outputs.items():
                ctx[k] = v
            session.completed_stages.append(stage_name)
            session.touch()

            yield {
                "type": "stage.done",
                "stage": stage_name,
                "outputs": list(outputs.keys()),
                "ts": time.time(),
            }

            # 红旗检查
            if contract.block_on_red_flag and ctx.get("red_flag"):
                yield {
                    "type": "scenario.done",
                    "status": "red_flag",
                    "detail": "intake 命中红旗，终止后续阶段",
                    "ts": time.time(),
                }
                return

        yield {
            "type": "scenario.done",
            "status": "ok",
            "ts": time.time(),
        }
