"""整改方案 v2.1 §2 — LLM 驱动的问诊规划

主路径：调 LLM 根据用户主诉 + 已答内容，动态生成下一批问题（1-N 个）
或判定信息已够。
兜底：rule-based 8 模板（LLM 不可用时降级）。

返回 IntakePlan：
  questions:        PlannedQuestion 列表
  is_complete:      True = 信息已够
  ready_to_run:     True = 立即可进 workflow
  reasoning:        整体判断理由
  next_action:      "answer" | "run" | "clarify"

S5 阶段：LLM 主路径 + JSON 强约束 + rule-based 兜底。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional

from .llm import chat_complete


log = logging.getLogger("intake_planner")


# ---------------------------------------------------------------------------
# 数据 schema
# ---------------------------------------------------------------------------
@dataclass
class PlannedQuestion:
    id: str
    text: str
    options: list[str]
    allow_free_text: bool = True
    required: bool = True
    rationale: str = ""
    multi: bool = False


@dataclass
class IntakePlan:
    questions: list[PlannedQuestion]
    is_complete: bool
    ready_to_run: bool
    reasoning: str
    next_action: str


# ---------------------------------------------------------------------------
# LLM 提示词
# ---------------------------------------------------------------------------
_PLANNER_SYSTEM = """你是 MetaClaw 系统的临床问诊规划助手。

任务：根据用户主诉和已采集信息，**动态判断**下一步该问什么。

判断规则：
1. **信息已够吗？** 已采集的信息是否足够让 4 个 specialist 开始工作？
   - 关键必答信息（年龄/性别/主诉持续时间/药物过敏）必须齐全
   - 缺少这些 → 必须继续问
2. **要问几个？** 1 个就够就问 1 个；最多 5 个；不需要凑数
3. **选项怎么给？**
   - 常见问题给 2-6 个候选 + 允许自由输入补充
   - 开放性问题可以给 0 个选项（纯自由输入）
4. **每题必须填 rationale**：为什么问这个（一句话给用户看）

**严格输出 JSON**，无任何额外文字：
{
  "questions": [
    {
      "id": "kebab-case-id",          // 稳定 id
      "text": "问题正文",
      "options": ["选项1", "选项2"],
      "allow_free_text": true,        // 是否允许自由输入补充
      "required": true,              // 是否必答
      "rationale": "为什么问这个（给用户看）",
      "multi": false                 // 是否多选
    }
  ],
  "is_complete": false,            // true = 信息已够，跳过问诊
  "reasoning": "整体判断理由（给用户看）"
}
"""


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------
async def _plan_with_llm(
    user_request: str,
    partial_qa: dict,
    history: list[dict],
) -> dict:
    """调 LLM 生成下一批问题。失败抛异常由上层降级。"""
    # 构造 user message
    qa_str = "\n".join(f"- {k}: {v}" for k, v in partial_qa.items() if v) or "（无）"
    history_str = "\n".join(
        f"- Q: {h.get('text','')} → A: {h.get('value','')}" for h in (history or [])
    ) or "（无）"
    user_msg = f"""用户主诉：{user_request}

已采集信息：
{qa_str}

历史问答：
{history_str}

请按 system 规则输出 JSON。"""
    raw = await chat_complete(
        messages=[
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=1500,
    )
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"LLM 没返回 JSON: {raw[:200]}")
    parsed = json.loads(m.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM returned non-dict JSON")
    return parsed


# ---------------------------------------------------------------------------
# Rule-based 兜底（与 S2 一致，加 rationale）
# ---------------------------------------------------------------------------
_CANDIDATE_QUESTIONS: list[PlannedQuestion] = [
    PlannedQuestion(
        id="age", text="患者多大年龄？",
        options=["0-3 岁", "3-6 岁", "6-12 岁", "12-18 岁", "18-65 岁", "65 岁以上"],
        rationale="年龄影响疾病谱和药物剂量",
    ),
    PlannedQuestion(
        id="gender", text="患者性别？",
        options=["男", "女", "其他 / 不愿透露"],
        rationale="性别影响部分疾病发病率",
    ),
    PlannedQuestion(
        id="main_symptom_duration", text="主要症状持续多久了？",
        options=["< 6 小时", "6-24 小时", "1-3 天", "3-7 天", "1 周-1 个月", "1 个月以上"],
        rationale="病程是区分急性/慢性的关键",
    ),
    PlannedQuestion(
        id="fever_temp", text="最高体温大概多少？",
        options=["< 37.5°C", "37.5-38°C", "38-38.5°C", "38.5-39°C", "39-40°C", "≥ 40°C", "没测过"],
        required=False, rationale="体温高度提示感染严重程度",
    ),
    PlannedQuestion(
        id="cough_type", text="咳嗽是干咳还是有痰？",
        options=["干咳无痰", "有痰（白痰）", "有痰（黄/绿痰）", "没咳嗽", "不确定"],
        required=False, rationale="咳嗽性质提示感染位置",
    ),
    PlannedQuestion(
        id="associated_symptoms", text="除了主诉外，还有哪些伴随症状？（可多选）",
        options=["鼻塞/流涕", "咽痛", "头痛", "乏力", "食欲下降", "呕吐", "腹泻", "皮疹"],
        multi=True, required=False, rationale="伴随症状帮助缩小鉴别诊断范围",
    ),
    PlannedQuestion(
        id="drug_allergy", text="既往有药物过敏吗？",
        options=["无", "青霉素类", "磺胺类", "阿司匹林", "其他（请用自由输入补充）"],
        rationale="过敏史直接影响药物选择",
    ),
    PlannedQuestion(
        id="past_history", text="既往有什么慢性病或长期用药？",
        options=["无", "高血压", "糖尿病", "哮喘", "心脏病", "其他（请用自由输入补充）"],
        required=False, rationale="既往史影响诊断方向",
    ),
]

_TRIGGER_KEYWORDS: dict[str, list[str]] = {
    "fever_temp": [r"发烧", r"发热", r"体温", r"烫"],
    "cough_type": [r"咳", r"嗽", r"痰"],
    "associated_symptoms": [],
    "drug_allergy": [],
    "past_history": [],
}

_MUST_ASK = {"age", "gender", "main_symptom_duration", "drug_allergy"}


def _should_ask(q: PlannedQuestion, user_request: str) -> bool:
    if q.id in _MUST_ASK:
        return True
    triggers = _TRIGGER_KEYWORDS.get(q.id, [])
    if not triggers:
        return True
    return any(re.search(t, user_request) for t in triggers)


def _plan_with_rules(
    user_request: str,
    partial_qa: dict,
    max_questions: int,
) -> IntakePlan:
    next_questions: list[PlannedQuestion] = []
    answered = {qid for qid, v in partial_qa.items() if v and v.strip()}
    missing_required: list[str] = []
    for q in _CANDIDATE_QUESTIONS:
        if q.id in answered:
            continue
        if not _should_ask(q, user_request):
            continue
        if q.required:
            missing_required.append(q.id)
        if len(next_questions) < max_questions:
            next_questions.append(q)
    is_complete = len(missing_required) == 0 and len(next_questions) == 0
    if is_complete:
        reasoning = "已采集全部必答信息，可以进入诊断（rule-based 兜底）"
    else:
        must = "、".join(missing_required[:3])
        reasoning = f"还缺必答信息（{must}...）（rule-based 兜底）"
    return IntakePlan(
        questions=next_questions,
        is_complete=is_complete,
        ready_to_run=is_complete,
        reasoning=reasoning,
        next_action="run" if is_complete else "answer",
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
async def generate_next_questions(
    user_request: str,
    partial_qa: dict,
    history: Optional[list[dict]] = None,
    max_questions: int = 5,
) -> IntakePlan:
    """生成下一批问诊问题（LLM 驱动，rule-based 兜底）。"""
    history = history or []

    # 主路径：LLM
    try:
        llm_result = await _plan_with_llm(user_request, partial_qa, history)
        questions = []
        for q in llm_result.get("questions", [])[:max_questions]:
            questions.append(PlannedQuestion(
                id=q.get("id", f"q{len(questions)}"),
                text=q["text"],
                options=q.get("options", []),
                allow_free_text=q.get("allow_free_text", True),
                required=q.get("required", True),
                rationale=q.get("rationale", ""),
                multi=q.get("multi", False),
            ))
        is_complete = bool(llm_result.get("is_complete", False))
        return IntakePlan(
            questions=questions,
            is_complete=is_complete,
            ready_to_run=is_complete or len(questions) == 0,
            reasoning=llm_result.get("reasoning", ""),
            next_action="run" if is_complete or not questions else "answer",
        )
    except Exception as e:
        log.warning(f"LLM planner 失败，降级 rule-based: {e}")
        return _plan_with_rules(user_request, partial_qa, max_questions)


def plan_to_dict(plan: IntakePlan) -> dict:
    return {
        "questions": [asdict(q) for q in plan.questions],
        "is_complete": plan.is_complete,
        "ready_to_run": plan.ready_to_run,
        "reasoning": plan.reasoning,
        "next_action": plan.next_action,
    }
