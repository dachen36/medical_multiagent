"""整改方案 S5-C — 智能建议生成

根据当前会话状态 + 阶段，生成 3 条 LLM-driven 的建议 chip。
用户可手动"🔄 换一批"（前端调 refresh=true 重新生成）。

S2 阶段：rule-based 起手（按 session 阶段返回固定 3 条）；
S5 阶段：调 LLM 生成（chat_complete）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional

from .llm import chat_complete
from .workflows import get_or_create_session


log = logging.getLogger("suggestions")


# 4 个建议模板（按用户上一轮反馈 — 主页底部留个"💡 试试"区）
# 首次访问 / pre_intake：3 个引导
# 有 session / post_intake：根据阶段推荐
TEMPLATES_BY_STAGE = {
    "pre_intake": [
        {"icon": "💊", "label": "试试问：布洛芬怎么吃？",
         "query": "儿童退烧药布洛芬的剂量和副作用是什么？", "intent": "follow_up_drug"},
        {"icon": "📚", "label": "试试问：什么是高血压",
         "query": "什么是高血压？发病机制和常见分型", "intent": "follow_up_knowledge"},
        {"icon": "🧬", "label": "查系统：学到了什么",
         "query": "系统学到了什么？当前的诊断模式有什么？", "intent": "meta_query"},
    ],
    "post_intake": [
        {"icon": "💊", "label": "用药复查",
         "query": "针对本次诊断，用药方面有什么建议？剂量和副作用如何？", "intent": "follow_up_drug"},
        {"icon": "🔬", "label": "重新评估",
         "query": "请基于现有病历，重新做一次鉴别诊断，看有没有遗漏。", "intent": "follow_up_diag"},
        {"icon": "📚", "label": "知识补充",
         "query": "补充一下相关医学知识，原理和最新指南。", "intent": "follow_up_knowledge"},
    ],
    "report_done": [
        {"icon": "💊", "label": "复查用药方案",
         "query": "针对最终报告里的药物建议，剂量和副作用能再详细吗？", "intent": "follow_up_drug"},
        {"icon": "🧬", "label": "看本次进化",
         "query": "本次诊断产生了什么进化？诊断模式匹配历史吗？", "intent": "meta_query"},
        {"icon": "📚", "label": "知识缺口补全",
         "query": "本次诊断暴露了哪些知识盲区？推荐补充哪些书籍？", "intent": "follow_up_knowledge"},
    ],
}


@dataclass
class Suggestion:
    icon: str
    label: str
    query: str
    intent: str


def _determine_stage(session_id: Optional[str]) -> str:
    """根据 session 状态判断 stage。"""
    if not session_id:
        return "pre_intake"
    s = get_or_create_session(session_id)
    has_patient = bool(s.ctx.get("patient_record"))
    has_report = bool(s.ctx.get("final_report"))
    if has_report:
        return "report_done"
    if has_patient:
        return "post_intake"
    return "pre_intake"


async def generate_suggestions(
    session_id: Optional[str] = None,
    refresh: bool = False,
    llm_generate: Optional[callable] = None,
) -> dict:
    """生成 3 条智能建议。

    Args:
        session_id: 当前 session（None=首次访问）
        refresh: 用户手动"换一批"，未来可加随机种子
        llm_generate: 可选 LLM 函数。签名 (stage, session_ctx) -> list[dict]

    Returns:
        { stage, suggestions: [...], source: "live" | "fallback" }
    """
    stage = _determine_stage(session_id)
    session_ctx = {}
    if session_id:
        s = get_or_create_session(session_id)
        # 只传部分 ctx 给 LLM（避免传太敏感的数据）
        session_ctx = {
            "has_patient_record": bool(s.ctx.get("patient_record")),
            "completed_stages": s.completed_stages[-5:],
            "round": s.round_no,
        }

    # 主路径：LLM
    if llm_generate is not None:
        try:
            llm_result = await llm_generate(stage, session_ctx)
            suggestions = [
                Suggestion(
                    icon=s.get("icon", "💡"),
                    label=s.get("label", s.get("query", "")[:20]),
                    query=s.get("query", ""),
                    intent=s.get("intent", "follow_up_diag"),
                )
                for s in llm_result[:3]
            ]
            if len(suggestions) == 3:
                return {
                    "stage": stage,
                    "suggestions": [asdict(s) for s in suggestions],
                    "source": "live",
                }
        except Exception as e:
            log.warning(f"LLM suggestions 失败，降级: {e}")

    # 兜底：rule-based 模板
    templates = TEMPLATES_BY_STAGE.get(stage, TEMPLATES_BY_STAGE["pre_intake"])

    # refresh=true 时打乱顺序（让"换一批"有感）
    if refresh:
        # 简单 shuffle: 反转
        templates = list(reversed(templates))

    suggestions = [Suggestion(**t) for t in templates]
    return {
        "stage": stage,
        "suggestions": [asdict(s) for s in suggestions],
        "source": "fallback",
    }
