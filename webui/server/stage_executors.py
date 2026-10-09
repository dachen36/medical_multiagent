"""整改方案 §B3 — Stage 执行器

把 workflow 5 个 stage 各自包装成 executor 函数，每个都：
  1. 构造合适的请求 prompt
  2. 调 run_agent_turn（已有）跑 specialist
  3. 把 agent.* 流式事件 put 到 stream_queue（让 UI 实时看到）
  4. 完成后返回 outputs dict（写入 ctx）

并行 stage（knowledge_analysis）通过 gather 内部并发启动两个 agent。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from . import agents_io
from .scenario_runner import _stream_with_timeout, run_agent_turn
from .workflows import SessionState


# ---------------------------------------------------------------------------
# 构造请求 prompt 的小工具
# ---------------------------------------------------------------------------
def _build_request(stage: str, ctx: dict[str, Any]) -> str:
    """根据 stage 构造 agent 看到的请求。"""
    user_request = ctx.get("user_request", "")
    intake_qa = ctx.get("intake_qa", {})
    patient = ctx.get("patient_record") or {}
    evidence = ctx.get("evidence") or ""
    ddx = ctx.get("ddx") or ""

    def _safe_str(v, default="(无)", maxlen=2000):
        """把 dict/list/None/str 安全地转字符串并截断。"""
        if v is None or v == "":
            return default
        if isinstance(v, (dict, list)):
            s = json.dumps(v, ensure_ascii=False, indent=2)
        else:
            s = str(v)
        return s[:maxlen]

    if stage == "intake":
        qa_str = json.dumps(intake_qa, ensure_ascii=False, indent=2) if intake_qa else "(无)"
        return (
            f"用户主诉：{user_request}\n\n"
            f"已知问诊信息：\n{qa_str}\n\n"
            "请按 9 段式问诊流程进行（如有缺失信息请继续问），"
            "完成后输出结构化 JSON {patient, chief_complaint, interview_sections, entities, next_step, red_flag}。"
        )

    if stage == "knowledge":
        entities = ctx.get("entities") or []
        entities_str = ", ".join(str(e) for e in entities) if entities else "(无)"
        return (
            f"用户主诉：{user_request}\n"
            f"病历：{json.dumps(patient, ensure_ascii=False)}\n"
            f"关键实体：{entities_str}\n\n"
            "请用 TOC + RAG + KG 三引擎搜索相关医学知识，输出 JSON "
            "{query, engines_used, toc_results, rag_results, kg_results, blind_spots, summary}。"
        )

    if stage == "analysis":
        return (
            f"用户主诉：{user_request}\n"
            f"病历：{json.dumps(patient, ensure_ascii=False)}\n"
            f"知识检索结果：{_safe_str(evidence, maxlen=2000)}\n\n"
            "请执行：1) 药物相互作用检查；2) 化验解读（如有）；3) 5 维度鉴别诊断；4) 认知偏差自检。"
            "输出 JSON {drug_interactions, lab_interpretation, differential_diagnosis, bias_check, self_evaluation}。"
        )

    if stage == "evolution":
        return (
            f"病历：{json.dumps(patient, ensure_ascii=False)}\n"
            f"鉴别诊断：{_safe_str(ddx, maxlen=2000)}\n"
            f"药物检查：{_safe_str(ctx.get('drug_check'), maxlen=1000)}\n\n"
            "请执行自我进化：1) 提取本次诊断模式三元组；2) 比对历史模式；3) 触发模式晋升（如果置信度达标）。"
            "输出 JSON {evolution_run, current_state, clinical_rules, memory_update}。"
        )

    if stage == "report":
        # 整改方案 §E1 — report prompt 重写：承上启下叙事报告，不是 4 份摘要拼接
        # 要求协调者按"工作流实际发生的经过"来叙述：
        #   - 知识智能体查了哪些书、查到了什么关键词
        #   - 分析智能体用什么机制（5 维度推理 / 药物库 / 化验规则）得到结论
        #   - 进化智能体提炼了什么规律、是否注入了 KG
        # 这样每个智能体"承上启下"，而非各说各话再被摘要。
        # §E3 — 用固定分隔符让前端能把"综合报告"和"系统自评"拆开。
        # S5-E — 增量更新模式（追问场景）：基于上一份报告做增量，不重头写
        if ctx.get("incremental_mode"):
            return _build_incremental_report_prompt(user_request, ctx)
        return (
            "你是 MetaClaw 的协调者。刚才 3 个 specialist 按工作流依次/并行完成了他们的工作，"
            "现在你要基于他们的**实际工作产物**写一份汇总报告。\n\n"
            "⚠️ 关键要求：这是一份「叙事报告」，不是「摘要拼接」。\n"
            "每个 specialist 不是孤立汇报，而是要体现**承上启下**："
            "上一个 specialist 的输出怎么被下一个 specialist 用上了。\n\n"
            "---\n"
            "## 原始主诉\n"
            f"{user_request}\n\n"
            "## 病历（问诊采集产物）\n"
            f"{json.dumps(patient, ensure_ascii=False, indent=2)}\n\n"
            "## 知识检索产物（knowledge-specialist 输出）\n"
            f"{_safe_str(evidence, maxlen=3000)}\n\n"
            "## 智能分析产物（analysis-specialist 输出）\n"
            f"药物互作检查：{_safe_str(ctx.get('drug_check'), maxlen=1200)}\n"
            f"化验解读：{_safe_str(ctx.get('lab_interp'), maxlen=1200)}\n"
            f"鉴别诊断：{_safe_str(ctx.get('ddx'), maxlen=2000)}\n"
            f"认知偏差自检：{_safe_str(ctx.get('bias_check'), maxlen=800)}\n\n"
            "## 知识盲区（knowledge-specialist 标记的证据不足处）\n"
            f"{_safe_str(ctx.get('blind_spots'), maxlen=1500)}\n\n"
            "## 自我进化产物（evolution-specialist 输出）\n"
            f"{_safe_str(ctx.get('evolution_state'), maxlen=2000)}\n\n"
            "---\n\n"
            "请严格按以下结构输出（用 markdown）。**第一行不要写代码块标记**。\n\n"
            "# 最终诊断报告\n\n"
            "## 工作流回顾\n"
            "一句话概括本次诊断走了哪几个阶段、各耗时多少（若不确定就写'约N秒'）、总体结论方向。\n\n"
            "## 问诊采集（intake）\n"
            "提炼病历关键点：患者画像、主诉、病程、过敏/既往史。一句话点出本次问诊是否有遗漏或红旗。\n\n"
            "## 知识检索（knowledge）\n"
            "**叙事**：knowledge 智能体针对哪些关键词、查询了哪些书（具体书名/章节）、三引擎分别命中多少条、"
            "最重要的发现是什么。如果触发了盲区补充，要说明补了什么。\n\n"
            "## 智能分析（analysis）\n"
            "**叙事**：analysis 智能体接收了上面的知识，采用了什么机制（5 维度推理 / drug_interaction_db / "
            "lab_interpreter 规则），最终主诊和次诊是什么、置信度多少、鉴别依据是什么。"
            "强调 analysis 是**站在 knowledge 肩膀上**做的判断，不是凭空诊断。\n\n"
            "## 自我进化（evolution）\n"
            "**叙事**：evolution 智能体从这次诊断中提取了什么模式（症状→诊断三元组），"
            "是否匹配到了历史模式簇、置信度如何、是否晋升为临床规律或注入了 KG。\n\n"
            "## 协调者建议\n"
            "面向患者/家属的**人话版**行动建议：下一步该怎么做、多久复查、什么情况要立即就医。"
            "必须以免责声明结尾。\n\n"
            "---META_REPORT_SPLIT---\n\n"
            "# 系统自评\n\n"
            "## 当前系统状态\n"
            "基于本次诊断，MetaClaw 当前的知识库规模、病历数、进化轮次（若 ctx 里有 evolution_state 就引用，否则留待用户在自评 tab 查看）。\n\n"
            "## 本次诊断暴露的知识缺口\n"
            "**重要**：上面有「知识盲区」一节，knowledge-specialist 标记了哪些关键词三引擎都没命中。"
            "**直接基于这个盲区列表**写推荐书目，不要凭感觉编。\n"
            "如果盲区为空（如「无」），说「本次诊断未暴露明显知识盲区」并跳过推荐书目。\n\n"
            "## 推荐补充书籍\n"
            "针对上面的知识缺口，推荐 1-3 本具体医学教材（书名 + 版本 + 为什么补这本）。\n"
            "格式：`1. 《书名》第N版 —— 补什么缺口`，每本一行。\n"
        )

    return user_request


# ---------------------------------------------------------------------------
# 单 agent stage executor
# ---------------------------------------------------------------------------
async def _run_single_agent_stage(
    stage_name: str,
    agent_name: str,
    ctx: dict,
    cancel: asyncio.Event,
    session: SessionState,
    queue: asyncio.Queue,
    histories: dict[str, list[dict]],
) -> dict:
    """一个 agent 跑一个 stage。"""
    # 找 agent
    all_agents = agents_io.list_agents()
    agent = next((a for a in all_agents if a.name == agent_name), None)
    if agent is None:
        await queue.put({
            "type": "stage.error",
            "stage": stage_name,
            "detail": f"agent not found: {agent_name}",
            "ts": time.time(),
        })
        return {}

    request = _build_request(stage_name, ctx)

    # 取/创建 history
    history = histories.setdefault(agent.name, [])

    # 发送 agent.start
    await queue.put({
        "type": "agent.start",
        "name": agent.name,
        "stage": stage_name,
        "color": agent.color,
        "ts": time.time(),
    })

    chunks: list[str] = []
    process_steps: list[dict] = []
    failed: str | None = None
    try:
        async for ev in run_agent_turn(agent, request, history=history, cancel=cancel):
            if ev["kind"] == "text":
                chunks.append(ev["delta"])
                await queue.put({
                    "type": "agent.token",
                    "name": agent.name,
                    "stage": stage_name,
                    "delta": ev["delta"],
                    "ts": time.time(),
                })
            elif ev["kind"] == "tool_call":
                await queue.put({
                    "type": "agent.tool_call",
                    "name": agent.name,
                    "stage": stage_name,
                    "tool_id": ev["id"],
                    "tool_name": ev["name"],
                    "tool_input": ev["input"],
                    "ts": time.time(),
                })
                process_steps.append({"id": ev["id"], "name": ev["name"], "input": ev["input"]})
            elif ev["kind"] == "tool_result":
                await queue.put({
                    "type": "agent.tool_result",
                    "name": agent.name,
                    "stage": stage_name,
                    "tool_id": ev["id"],
                    "tool_name": ev["name"],
                    "output": ev["output"],
                    "is_error": ev["is_error"],
                    "ts": time.time(),
                })
                for s in process_steps:
                    if s.get("id") == ev["id"]:
                        s["output"] = ev["output"]
                        s["is_error"] = ev["is_error"]
            elif ev["kind"] == "plan_return":
                await queue.put({
                    "type": "agent.plan_return",
                    "name": agent.name,
                    "stage": stage_name,
                    "rev": ev["rev"],
                    "todos": ev["todos"],
                    "ts": time.time(),
                })
            elif ev["kind"] == "step_status":
                await queue.put({
                    "type": "agent.step_status",
                    "name": agent.name,
                    "stage": stage_name,
                    "step_id": ev["step_id"],
                    "status": ev["status"],
                    "result": ev.get("result"),
                    "error": ev.get("error"),
                    "ts": time.time(),
                })
            elif ev["kind"] == "agent_done":
                break
            elif ev["kind"] == "agent_error":
                failed = ev["detail"]
                break
    except Exception as e:
        failed = f"{type(e).__name__}: {e}"

    if failed is not None:
        await queue.put({
            "type": "agent.error",
            "name": agent.name,
            "stage": stage_name,
            "detail": failed,
            "ts": time.time(),
        })
        return {}

    full_text = "".join(chunks)
    await queue.put({
        "type": "agent.done",
        "name": agent.name,
        "stage": stage_name,
        "text": full_text,
        "ts": time.time(),
    })

    # 解析 agent 的输出（如果 LLM 输出包含 JSON）
    parsed = _try_parse_agent_output(full_text, stage_name)

    return {
        f"{stage_name}_output": full_text,
        f"{stage_name}_text": full_text,
        f"{stage_name}_parsed": parsed,
        **parsed,  # 平铺 parsed 里的字段（如 patient_record, evidence, ddx, ...）
    }


# ---------------------------------------------------------------------------
# 并行 stage executor
# ---------------------------------------------------------------------------
async def knowledge_analysis_executor(
    ctx: dict,
    cancel: asyncio.Event,
    session: SessionState,
    queue: asyncio.Queue,
    histories: dict[str, list[dict]] | None = None,
) -> dict:
    """知识 + 分析 并行 stage。"""
    histories = histories or {}
    results = await asyncio.gather(
        _run_single_agent_stage("knowledge", "knowledge-specialist", ctx, cancel, session, queue, histories),
        _run_single_agent_stage("analysis", "analysis-specialist", ctx, cancel, session, queue, histories),
        return_exceptions=True,
    )
    out: dict = {}
    for r in results:
        if isinstance(r, Exception):
            continue
        if isinstance(r, dict):
            out.update(r)
    return out


# ---------------------------------------------------------------------------
# 单 agent stage executors（包装 _run_single_agent_stage）
# ---------------------------------------------------------------------------
async def intake_executor(
    ctx: dict, cancel: asyncio.Event, session: SessionState,
    queue: asyncio.Queue, histories: dict[str, list[dict]] | None = None,
) -> dict:
    histories = histories or {}
    out = await _run_single_agent_stage(
        "intake", "intake-specialist", ctx, cancel, session, queue, histories,
    )
    return out


async def knowledge_executor(
    ctx: dict, cancel: asyncio.Event, session: SessionState,
    queue: asyncio.Queue, histories: dict[str, list[dict]] | None = None,
) -> dict:
    histories = histories or {}
    return await _run_single_agent_stage(
        "knowledge", "knowledge-specialist", ctx, cancel, session, queue, histories,
    )


async def analysis_executor(
    ctx: dict, cancel: asyncio.Event, session: SessionState,
    queue: asyncio.Queue, histories: dict[str, list[dict]] | None = None,
) -> dict:
    histories = histories or {}
    return await _run_single_agent_stage(
        "analysis", "analysis-specialist", ctx, cancel, session, queue, histories,
    )


async def evolution_executor(
    ctx: dict, cancel: asyncio.Event, session: SessionState,
    queue: asyncio.Queue, histories: dict[str, list[dict]] | None = None,
) -> dict:
    histories = histories or {}
    return await _run_single_agent_stage(
        "evolution", "evolution-specialist", ctx, cancel, session, queue, histories,
    )


async def report_executor(
    ctx: dict, cancel: asyncio.Event, session: SessionState,
    queue: asyncio.Queue, histories: dict[str, list[dict]] | None = None,
) -> dict:
    histories = histories or {}
    out = await _run_single_agent_stage(
        "report", "team-coordinator", ctx, cancel, session, queue, histories,
    )
    return out


# ---------------------------------------------------------------------------
# 默认 executor 集合
# ---------------------------------------------------------------------------
def default_executors() -> dict[str, Any]:
    """默认所有 stage 用的 executor 集合。"""
    return {
        "intake": intake_executor,
        "knowledge": knowledge_executor,
        "analysis": analysis_executor,
        "knowledge_analysis": knowledge_executor,  # 占位；并行的真执行在 knowledge_analysis_executor
        "evolution": evolution_executor,
        "report": report_executor,
    }


# ---------------------------------------------------------------------------
# 工具：尝试解析 agent 输出中的 JSON
# ---------------------------------------------------------------------------
def _try_parse_agent_output(text: str, stage: str) -> dict:
    """从 LLM 输出文本中尝试提取 JSON。

    兼容几种格式：
      1) 纯 JSON
      2) ```json ... ``` 块
      3) 输出混在 markdown 中（用 { 找第一个 {，匹配闭合括号）

    解析成功后按 stage 决定哪些字段平铺到 ctx：
      - intake   → patient_record, entities, red_flag, interview_done
      - knowledge → evidence, blind_spots
      - analysis  → drug_check, lab_interp, ddx, bias_check
      - evolution → evolution_state, pattern_hits
      - report    → final_report, self_assessment
    """
    parsed: dict = {}
    if not text:
        return parsed

    # 找 ```json ... ``` 块
    import re
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else None
    if not candidate:
        # 找第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
    if not candidate:
        return parsed
    try:
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            return {}
    except Exception:
        return {}

    # 字段重命名（避免和 stage 自己的 _output/_text 冲突）
    rename_map = {
        "intake": [
            ("patient", "patient_record"),
            ("chief_complaint", "chief_complaint"),
            ("interview_sections", "interview_sections"),
            ("entities", "entities"),
            ("red_flag", "red_flag"),
        ],
        "knowledge": [
            ("summary", "evidence"),
            ("blind_spots", "blind_spots"),
            ("kg_results", "kg_hits"),
        ],
        "analysis": [
            ("drug_interactions", "drug_check"),
            ("lab_interpretation", "lab_interp"),
            ("differential_diagnosis", "ddx"),
            ("bias_check", "bias_check"),
            ("self_evaluation", "self_evaluation"),
        ],
        "evolution": [
            ("evolution_run", "evolution_run"),
            ("current_state", "evolution_state"),
            ("clinical_rules", "pattern_hits"),
        ],
        "report": [
            ("final_report", "final_report"),
            ("self_assessment", "self_assessment"),
        ],
    }
    out: dict = {}
    for src, dst in rename_map.get(stage, []):
        if src in parsed:
            out[dst] = parsed[src]
    return out


# ---------------------------------------------------------------------------
# S5-E — 增量报告 prompt（追问场景）
# ---------------------------------------------------------------------------
def _build_incremental_report_prompt(user_request: str, ctx: dict) -> str:
    """增量更新模式 prompt。

    场景：用户对已有病历追问（如"退烧药选什么"）。
    协调者：基于 ctx 中已有的 patient_record/evidence/ddx/evolution_state + 用户新问题，
    输出一份【增量更新】报告。
    - 保留上一份报告的核心结论
    - 重点回答用户的追问
    - 用 ---META_REPORT_SPLIT--- 同样切两段（综合 + 自评）
    """
    patient = ctx.get("patient_record") or {}
    last_report = ctx.get("final_report", "(无上一份报告)")
    evidence = ctx.get("evidence", "")
    ddx = ctx.get("ddx", "")
    evolution = ctx.get("evolution_state", "")

    def _s(v, default="(无)", maxlen=2000):
        if v is None or v == "" or v == {}:
            return default
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False, indent=2)[:maxlen]
        return str(v)[:maxlen]

    return (
        "你是 MetaClaw 的协调者。用户对**已有病历**提出了追问，"
        "这是一次**增量更新**，不是重头诊断。\n\n"
        "**用户本次提问：**\n"
        f"{user_request}\n\n"
        "**已有病历：**\n"
        f"{_s(patient)}\n\n"
        "**已有的知识证据（上一轮）：**\n"
        f"{_s(evidence, maxlen=2000)}\n\n"
        "**已有的鉴别诊断（上一轮）：**\n"
        f"{_s(ddx, maxlen=2000)}\n\n"
        "**已有的进化记录（上一轮）：**\n"
        f"{_s(evolution, maxlen=1500)}\n\n"
        "**上一份最终报告（要保留核心结论）：**\n"
        f"{_s(last_report, maxlen=3000)}\n\n"
        "---\n\n"
        "请严格按以下结构输出（用 markdown）：\n\n"
        "# 最终诊断报告（增量更新 · 第 N 轮）\n\n"
        "## 📌 上一份结论回顾\n"
        "用 1-2 句话回顾上一份报告的核心结论，**不要重写**。\n\n"
        "## 🆕 本次追问回应\n"
        "针对用户本次提问给出**直接回答**。\n"
        "可以调用已有病历 / 证据 / 鉴别诊断 / 进化记录中的信息。\n"
        "如果涉及新发现（如新的药物/检查/鉴别点），明确标出**新增**内容。\n\n"
        "## 🔄 结论更新\n"
        "如果本次回答改变了上一份报告的结论（如更换主诊、调整药物、补充鉴别点），"
        "说明**变什么**和**为什么**。\n"
        "如果没有改变，简短说「本次未改变上一份结论」。\n\n"
        "## ⚠️ 医疗免责声明\n"
        "⚠️ 本结论仅供参考，不构成专业医疗建议。\n\n"
        "---META_REPORT_SPLIT---\n\n"
        "# 系统自评\n\n"
        "## 本次追问是否暴露新的知识盲区\n"
        "基于用户的追问，简短指出是否需要补充知识（1-2 句话即可）。\n"
    )
