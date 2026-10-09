"""整改方案 v2.1 §1 — 入口意图分类（LLM 驱动）

主路径：调用 LLM 判定用户的 intent。
兜底：rule-based 关键词匹配（LLM 不可用 / 报错时降级）。

返回 ClassificationResult：
  is_medical:        是否医疗相关
  l1_intent:         L1 分类（医疗/非医疗/闲聊/...）
  needs_intake:      是否需要进入问诊
  l2_intent:         medical 子类（追问用药/追问知识/...）
  stages:            要执行的 stage 列表
  reasoning:         分类理由（前端展示）
  confidence:        0-1
  followup_hint:     追问场景给用户的引导语

S5 阶段主路径：LLM 调一次 chat_complete，prompt + JSON schema 强约束。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional

from .llm import chat_complete
from .workflows import (
    Intent, classify_intent as workflows_classify_intent,
    stages_for_intent, get_or_create_session,
)


log = logging.getLogger("intake_classifier")


class L1Intent(str, Enum):
    MEDICAL_DIAGNOSIS = "medical_diagnosis"
    MEDICAL_FOLLOWUP = "medical_followup"
    MEDICAL_KNOWLEDGE = "medical_knowledge"
    MEDICAL_META = "medical_meta"
    NON_MEDICAL = "non_medical"
    CHITCHAT = "chitchat"


# ---------------------------------------------------------------------------
# LLM 提示词
# ---------------------------------------------------------------------------
_CLASSIFY_SYSTEM = """你是 MetaClaw 医疗多智能体系统的入口分类器。
判断用户输入的 intent 并输出严格 JSON。

分类维度：
  1. is_medical: 是否为医疗相关请求
     - 医疗症状/疾病/药物/化验/检查/知识科普/病历查询/系统元信息查询 → true
     - 闲聊/天气/财经/创作/翻译/游戏/其它非医疗 → false
  2. 如果 is_medical=true，识别子意图：
     - medical_diagnosis: 临床诊断请求（描述症状/疼痛/不适/化验结果等，需要诊断）
     - medical_followup: 已有病历的追问（"这个药怎么吃"/"重新评估"/"补充知识"等）
     - medical_knowledge: 纯医学知识科普（"什么是高血压"，无具体患者）
     - medical_meta: 系统状态查询（"学到了什么"/"哪些病历"等）
  3. needs_intake: 是否需要进入问诊流程收集更多信息
     - medical_diagnosis + 无已有病历 → true
     - medical_followup / medical_knowledge / medical_meta → false
  4. stages: 需要执行的 workflow stages 列表
     - medical_diagnosis → ["intake", "knowledge_analysis", "evolution", "report"]
     - medical_followup（用药）→ ["analysis"]
     - medical_followup（评估/重新）→ ["knowledge_analysis", "report"]
     - medical_followup（知识补充）→ ["knowledge"]
     - medical_meta → ["evolution"]

**严格输出 JSON**，无任何额外文字：
{
  "is_medical": bool,
  "l1_intent": "medical_diagnosis" | "medical_followup" | "medical_knowledge" | "medical_meta" | "non_medical" | "chitchat",
  "needs_intake": bool,
  "l2_intent": "new_case" | "follow_up_drug" | "follow_up_knowledge" | "follow_up_diag" | "meta_query" | "",
  "stages": [str, ...],
  "reasoning": "一句话说明判断理由",
  "confidence": 0.0-1.0
}
"""


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
@dataclass
class ClassificationResult:
    is_medical: bool
    l1_intent: str
    needs_intake: bool
    l2_intent: str
    stages: list[str]
    reasoning: str
    confidence: float
    followup_hint: str


# ---------------------------------------------------------------------------
# LLM 分类调用
# ---------------------------------------------------------------------------
async def _classify_with_llm(user_request: str, has_session: bool) -> dict:
    """调用 LLM 做意图分类。失败抛异常由上层降级。"""
    session_hint = "用户已有病历上下文" if has_session else "用户无病历上下文（首次问诊）"
    user_msg = f"""{session_hint}

用户输入：{user_request}

请按 system 中的规则输出 JSON。"""
    raw = await chat_complete(
        messages=[
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=400,
    )
    # 尝试从 raw 中提取 JSON（兼容 LLM 偶尔加 ```json 包裹）
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"LLM 没返回 JSON: {raw[:200]}")
    parsed = json.loads(m.group(0))
    # 校验
    if not isinstance(parsed, dict):
        raise ValueError("LLM returned non-dict JSON")
    return parsed


# ---------------------------------------------------------------------------
# Rule-based 兜底（仅 LLM 不可用时）
# ---------------------------------------------------------------------------
_NON_MEDICAL_TOKENS = {
    "你好", "hi", "hello", "在吗", "你是谁", "你能做什么",
    "今天天气", "明天天气", "天气怎么样", "下雨", "晴天",
    "股票", "基金", "投资", "理财", "房价", "车价",
    "帮我写", "翻译", "总结", "写一篇", "讲个笑话",
    "打游戏", "电视剧", "电影", "音乐",
}

_CHITCHAT_PATTERNS = [
    r"^你好[\?\？\s]*$",
    r"^hi\s*[\?\？\s]*$",
    r"^hello\s*[\?\？\s]*$",
    r"^在吗[\?\？\s]*$",
]


def _is_chitchat(text: str) -> bool:
    text = text.strip()
    if len(text) > 12:
        return False
    for p in _CHITCHAT_PATTERNS:
        if re.match(p, text, re.IGNORECASE):
            return True
    return False


def _is_non_medical(text: str) -> bool:
    text_lower = text.lower()
    for kw in _NON_MEDICAL_TOKENS:
        if kw in text or kw.lower() in text_lower:
            return True
    return False


_NEW_CASE_MARKERS = [
    r"今天开始", r"今天刚", r"今早", r"昨晚开始", r"刚刚",
    r"新发", r"新出现", r"刚开始",
]


def _looks_like_new_diagnosis(text: str) -> bool:
    for marker in _NEW_CASE_MARKERS:
        if re.search(marker, text):
            return True
    return False


def _classify_with_rules(
    user_request: str,
    has_session: bool,
) -> ClassificationResult:
    """rule-based 兜底分类。"""
    user = user_request.strip()

    if _is_chitchat(user):
        return ClassificationResult(
            is_medical=False, l1_intent=L1Intent.CHITCHAT.value,
            needs_intake=False, l2_intent="", stages=[],
            reasoning="这是闲聊问候（兜底分类）", confidence=0.7,
            followup_hint="",
        )

    if _is_non_medical(user):
        return ClassificationResult(
            is_medical=False, l1_intent=L1Intent.NON_MEDICAL.value,
            needs_intake=False, l2_intent="", stages=[],
            reasoning="这是非医疗请求（兜底分类）", confidence=0.7,
            followup_hint="",
        )

    # 医疗信号：有 session + 不像新病例 → 追问
    if has_session and not _looks_like_new_diagnosis(user):
        l2 = workflows_classify_intent(user, has_patient_record=True, round_no=2)
        return ClassificationResult(
            is_medical=True, l1_intent=L1Intent.MEDICAL_FOLLOWUP.value,
            needs_intake=False, l2_intent=l2.value,
            stages=stages_for_intent(l2),
            reasoning=f"已有病历，识别为追问（{l2.value}，兜底分类）",
            confidence=0.65, followup_hint=_followup_hint(l2),
        )

    # 医疗信号 + 无 session / 看起来新病例 → 进问诊
    # 规则版把任何"看起来有医疗关键字"的请求都当诊断
    return ClassificationResult(
        is_medical=True, l1_intent=L1Intent.MEDICAL_DIAGNOSIS.value,
        needs_intake=True, l2_intent=Intent.NEW_CASE.value,
        stages=stages_for_intent(Intent.NEW_CASE),
        reasoning="疑似医疗诊断请求（兜底分类）",
        confidence=0.55, followup_hint="",
    )


def _followup_hint(intent: Intent) -> str:
    hints = {
        Intent.FOLLOW_UP_DRUG:      "将基于当前病历做用药复查",
        Intent.FOLLOW_UP_KNOWLEDGE: "将基于当前病历做知识补充",
        Intent.FOLLOW_UP_DIAG:      "将基于当前病历做重新评估",
        Intent.META_QUERY:         "将查询本系统的进化状态",
    }
    return hints.get(intent, "")


# ---------------------------------------------------------------------------
# 入口函数
# ---------------------------------------------------------------------------
async def classify_request(
    user_request: str,
    session_id: Optional[str] = None,
) -> ClassificationResult:
    """入口意图分类（LLM 为主，rule-based 兜底）。"""
    user = (user_request or "").strip()
    if not user:
        return ClassificationResult(
            is_medical=False, l1_intent=L1Intent.NON_MEDICAL.value,
            needs_intake=False, l2_intent="", stages=[],
            reasoning="空输入", confidence=1.0, followup_hint="",
        )

    has_session = False
    if session_id:
        s = get_or_create_session(session_id)
        has_session = bool(s.ctx.get("patient_record"))

    # 主路径：LLM
    try:
        llm_result = await _classify_with_llm(user, has_session)
        return ClassificationResult(
            is_medical=bool(llm_result.get("is_medical", False)),
            l1_intent=str(llm_result.get("l1_intent", "non_medical")),
            needs_intake=bool(llm_result.get("needs_intake", False)),
            l2_intent=str(llm_result.get("l2_intent", "")),
            stages=list(llm_result.get("stages", [])),
            reasoning=str(llm_result.get("reasoning", "")),
            confidence=float(llm_result.get("confidence", 0.7)),
            followup_hint="",
        )
    except Exception as e:
        log.warning(f"LLM classify 失败，降级 rule-based: {e}")
        return _classify_with_rules(user, has_session)


def result_to_dict(r: ClassificationResult) -> dict:
    return asdict(r)
