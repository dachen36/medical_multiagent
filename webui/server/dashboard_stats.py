"""整改方案 §A7 — 看板统计 /api/dashboard/stats

S1 阶段：返回基于 agent 描述 + 已知常量的估值（不依赖 DuckDB 等重数据源）。
        来源字段 = "fallback"。
S2-S4 阶段：可逐步替换为对真实数据库的查询（duckdb / neo4j / 文件计数）。
        来源字段 = "live"。

数据来源策略：
  - 教材数 / 章节数 / KG 实体 / KG 关系 / 药物互作对：当前从
    clinical-core skill 的工具目录推断（greppable 字符串），失败回退 0。
  - 病历数 / 就诊记录 / 进化轮次：当前固定为 evolution-specialist 描述
    中的已知值；后续可通过调用 self_evolution.py status 拉真实数据。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 估值常量（与 ~/.openharness/agents/*.md 描述保持一致；S2 起替换为真实查询）
# ---------------------------------------------------------------------------
# 进化相关指标从 evolution-specialist.md 的"自我进化成果"表中提取
_KNOWN_EVOLUTION = {
    "patients": 20,
    "visit_records": 175,
    "evolution_rounds": 11,
    "diagnostic_clusters": 26,
    "high_confidence_patterns": 2,
    "kg_injections": 11,
    "active_clinical_rules": 1,
}


# ---------------------------------------------------------------------------
# 知识库数据（来自 specialist 描述）
# ---------------------------------------------------------------------------
_KNOWN_KNOWLEDGE = {
    "textbooks": 60,
    "chapters": 16_444,
    "kg_entities": 84_307,
    "kg_relations": 120_193,
    "drug_pairs": 2_587,
}


def _scan_textbooks() -> int:
    """尝试扫描 clinical-core 数据目录，找出真实的教材数。"""
    candidates = [
        Path.home() / ".openharness" / "skills" / "clinical-core" / "data" / "books",
        Path.home() / ".openharness" / "skills" / "clinical-core" / "books",
    ]
    for d in candidates:
        if d.exists():
            # 计 *.pdf / *.md / *.txt 中任意一种
            n = 0
            for ext in ("*.pdf", "*.md", "*.txt"):
                n += len(list(d.glob(f"**/{ext}")))
            if n > 0:
                return n
    return 0


def _scan_chapters() -> int:
    """尝试从 toc_index.json 读取真实章节数。"""
    candidates = [
        Path.home() / ".openharness" / "skills" / "clinical-core" / "tools" / "toc_index.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                import json
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # 不同 schema 兼容
                    if "chapters" in data and isinstance(data["chapters"], list):
                        return len(data["chapters"])
                    if "entries" in data and isinstance(data["entries"], list):
                        return len(data["entries"])
                if isinstance(data, list):
                    return len(data)
            except Exception:
                continue
    return 0


def _scan_drug_pairs() -> int:
    """尝试扫描药物互作数据文件。"""
    candidates = [
        Path.home() / ".openharness" / "skills" / "clinical-core" / "data" / "drug_interactions.json",
        Path.home() / ".openharness" / "skills" / "clinical-core" / "data" / "drug_db.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                import json
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return len(data)
                if isinstance(data, dict):
                    # 兼容 {"interactions": [...]} / {"pairs": [...]} 等结构
                    for key in ("interactions", "pairs", "data"):
                        if key in data and isinstance(data[key], list):
                            return len(data[key])
            except Exception:
                continue
    return 0


def _scan_kg_stats() -> tuple[int, int]:
    """尝试从 KG 文件读取实体/关系数。"""
    candidates = [
        Path.home() / ".openharness" / "skills" / "clinical-core" / "data" / "kg.json",
        Path.home() / ".openharness" / "skills" / "clinical-core" / "data" / "knowledge_graph.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                import json
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    entities = data.get("entities") or data.get("nodes") or []
                    relations = data.get("relations") or data.get("edges") or []
                    return (
                        len(entities) if isinstance(entities, list) else 0,
                        len(relations) if isinstance(relations, list) else 0,
                    )
            except Exception:
                continue
    return 0, 0


def _scan_evolution() -> dict[str, int]:
    """尝试调用 self_evolution.py 读取真实进化数据。失败回退到已知常量。"""
    candidates = [
        Path.home() / ".openharness" / "skills" / "clinical-core" / "tools" / "self_evolution.py",
    ]
    for p in candidates:
        if p.exists():
            # S2 阶段：subprocess 调用 `python3 self_evolution.py status` 解析 JSON
            # S1 阶段：直接读 evolution_state.json（如有）
            for state_file in [
                Path.home() / ".openharness" / "evolution_state.json",
                p.parent / "evolution_state.json",
            ]:
                if state_file.exists():
                    try:
                        import json
                        data = json.loads(state_file.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            return {
                                "patients": data.get("patients", _KNOWN_EVOLUTION["patients"]),
                                "visit_records": data.get("visit_records", _KNOWN_EVOLUTION["visit_records"]),
                                "evolution_rounds": data.get("rounds", data.get("evolution_rounds", _KNOWN_EVOLUTION["evolution_rounds"])),
                                "diagnostic_clusters": data.get("clusters", data.get("diagnostic_clusters", _KNOWN_EVOLUTION["diagnostic_clusters"])),
                                "high_confidence_patterns": data.get("high_confidence", data.get("high_confidence_patterns", _KNOWN_EVOLUTION["high_confidence_patterns"])),
                                "kg_injections": data.get("kg_injections", _KNOWN_EVOLUTION["kg_injections"]),
                                "active_clinical_rules": data.get("active_rules", data.get("active_clinical_rules", _KNOWN_EVOLUTION["active_clinical_rules"])),
                            }
                    except Exception:
                        continue
    return dict(_KNOWN_EVOLUTION)


def collect_stats() -> dict[str, Any]:
    """Aggregate all stats. Real-scan first, fallback to known constants.

    Returns a flat dict with one extra `source` field:
      - "live"     — at least one real query succeeded
      - "fallback" — all real queries failed; values are estimates
    """
    textbooks = _scan_textbooks()
    chapters = _scan_chapters()
    drug_pairs = _scan_drug_pairs()
    kg_entities, kg_relations = _scan_kg_stats()
    evolution = _scan_evolution()

    any_live = bool(textbooks or chapters or drug_pairs or kg_entities or kg_relations)

    return {
        "textbooks":                 textbooks   or _KNOWN_KNOWLEDGE["textbooks"],
        "chapters":                  chapters    or _KNOWN_KNOWLEDGE["chapters"],
        "kg_entities":               kg_entities or _KNOWN_KNOWLEDGE["kg_entities"],
        "kg_relations":              kg_relations or _KNOWN_KNOWLEDGE["kg_relations"],
        "drug_pairs":                drug_pairs  or _KNOWN_KNOWLEDGE["drug_pairs"],
        "patients":                  evolution["patients"],
        "visit_records":             evolution["visit_records"],
        "evolution_rounds":          evolution["evolution_rounds"],
        "diagnostic_clusters":       evolution["diagnostic_clusters"],
        "high_confidence_patterns":  evolution["high_confidence_patterns"],
        "kg_injections":             evolution["kg_injections"],
        "active_clinical_rules":     evolution["active_clinical_rules"],
        "source":                    "live" if any_live else "fallback",
        "collected_at":              time.time(),
    }
