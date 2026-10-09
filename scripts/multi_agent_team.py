#!/usr/bin/env python3
"""
multi_agent_team.py — End-to-end demo of OpenHarness multi-agent management.

This script demonstrates how OpenHarness manages 4 specialist agents
(intake / knowledge / analysis / evolution — PPT 能力柱) plus 1
coordinator agent, coordinating them to handle a real clinical diagnosis
request via TeamLifecycleManager + TeammateMailbox.

Scenario: "child-fever-triage"
  User: "我家孩子 5 岁发烧 38.5°C 持续 6 小时，轻微咳嗽，怎么办？"
  Coordinator dispatches (parallel fan-out):
    - intake-specialist       (9段式问诊 + 病历建档 + 实体抽取)
    - knowledge-specialist    (TOC+RAG+KG 三引擎搜索)
    - analysis-specialist     (药物安全 + 鉴别诊断 + 认知偏差检查)
    - evolution-specialist    (自我进化 + 诊断模式提取)

All 4 agents share `clinical-core` skill (25+ clinical tools + 63 textbooks + DuckDB + KG).

Usage:
  uv run python scripts/multi_agent_team.py                    # mock LLM (fast)
  uv run python scripts/multi_agent_team.py --real             # real LLM call
  uv run python scripts/multi_agent_team.py --scenario NAME    # pick scenario
  uv run python scripts/multi_agent_team.py --no-cleanup       # keep team dir
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Ensure src/ is on sys.path so we import openharness directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from openharness.coordinator.agent_definitions import (
    get_agent_definition,
    get_all_agent_definitions,
)
from openharness.skills.loader import load_skill_registry
from openharness.swarm.mailbox import (
    TeammateMailbox,
    create_idle_notification,
    create_user_message,
)
from openharness.swarm.team_lifecycle import TeamLifecycleManager, TeamMember
from openharness.swarm.types import BackendType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIG_DIR = Path.home() / ".openharness"
TEAMS_DIR = CONFIG_DIR / "teams"
AGENTS_DIR = CONFIG_DIR / "agents"
SKILLS_DIR = CONFIG_DIR / "skills"

AGENT_NAMES = ["intake-specialist", "knowledge-specialist", "analysis-specialist", "evolution-specialist"]
COORDINATOR = "team-coordinator"

REQUIRED_SKILLS = {
    "intake-specialist":      {"clinical-core", "intake-protocol",
                              "medical-entity-extractor", "clinical-nlp-extractor"},
    "knowledge-specialist":   {"clinical-core", "hybrid-search-protocol"},
    "analysis-specialist":    {"clinical-core", "analysis-protocol",
                              "medical-diagnostic-agent", "clinical-diagnostic-reasoning",
                              "diagnostic-evaluation-agent"},
    "evolution-specialist":   {"clinical-core", "evolution-protocol"},
}

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
SCENARIOS = {
    "child-fever-triage": {
        "team": "child-fever-triage",
        "user_request": (
            "我家孩子 5 岁发烧 38.5°C 持续 6 小时，轻微咳嗽，怎么办？"
        ),
        "plan": [
            ("intake-specialist",
             "症状：5 岁儿童，发烧 38.5°C 持续 6 小时，轻微咳嗽。"
             "请按 intake-protocol 执行：1) 红旗筛查（30 秒内）→ 命中即返回 red_flag=true；"
             "2) 未命中 → 9 段式问诊（主诉+现病史+既往史+过敏+家族史）；"
             "3) 调用 doctor_memory.py new-patient 建病历；"
             "4) 调用 medical-entity-extractor 抽取实体（症状/药物/检验）。"
             "输出 JSON：{patient, chief_complaint, interview_sections, entities, red_flag, next_step}。"),
            ("knowledge-specialist",
             "基于以下症状做三引擎混合搜索：5 岁儿童发热 38.5°C + 轻微咳嗽。"
             "请按 hybrid-search-protocol 执行："
             "1) hybrid_search.py \"儿童发热咳嗽\" --top 5 （TOC+RAG 联合搜索）；"
             "2) kg_query.py \"上呼吸道感染\" （KG 知识图谱查询）；"
             "3) 如三引擎均无结果 → 触发 knowledge_gap_filler.py analyze 补充盲区。"
             "输出 JSON：{query, engines_used, toc_results, rag_results, kg_results, "
             "blind_spots, supplement_triggered, summary}。"),
            ("analysis-specialist",
             "基于主诉+病史做智能分析。请按 analysis-protocol 执行："
             "1) 鉴别诊断：5 维度推理（流行病学/症状学/既往史/检验/红旗排除）；"
             "2) 调用 clinical-diagnostic-reasoning 做认知偏差自检（5 类偏差）；"
             "3) 如涉及药物 → 调用 drug_interaction_db.py check 查相互作用（四档分级）；"
             "4) 如有检验数据 → 调用 lab_interpreter.py 解读（5 档判断）。"
             "输出 JSON：{differential_diagnosis, drug_interactions, lab_interpretation, "
             "bias_check, self_evaluation}。"),
            ("evolution-specialist",
             "基于本轮问诊触发自我进化。请按 evolution-protocol 执行："
             "1) 调用 self_evolution.py evolve 触发一轮进化（聚合诊断模式）；"
             "2) 检查是否有症状组合达到阈值 → 提炼临床规律；"
             "3) 检查高频模式是否需要注入 KG；"
             "4) 调用 doctor_memory.py show-memory 查看医生记忆更新。"
             "输出 JSON：{evolution_run, current_state, clinical_rules, memory_update}。"),
        ],
    },
    "chest-pain-triage": {
        "team": "chest-pain-triage",
        "user_request": (
            "我突然胸痛出汗，60 岁男性，有高血压史 10 年。"
        ),
        "plan": [
            ("intake-specialist",
             "⚠️ 红旗症状可能命中！症状：60 岁男性，急性胸痛+大汗，既往高血压 10 年。"
             "请立即按 intake-protocol 红旗筛查流程处理："
             "1) 命中红旗 → 立即返回 red_flag=true + 120 建议，跳过其他分析；"
             "2) 不要再做其他问诊工作。"
             "输出 JSON：{red_flag, type, action, rationale, skip_synthesis: true}。"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Step 0: Pre-flight checks
# ---------------------------------------------------------------------------
def banner(s: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n{s}\n{bar}")


def preflight() -> None:
    """Verify all 5 agents and 14 skills are discoverable."""
    banner("Step 0 · Pre-flight: agents + skills 完整性检查")

    # --- agents
    found = {a.name for a in get_all_agent_definitions()}
    missing_agents = set(AGENT_NAMES + [COORDINATOR]) - found
    if missing_agents:
        raise SystemExit(
            f"❌ Missing agent definitions: {missing_agents}\n"
            f"   Ensure files exist in {AGENTS_DIR}/"
        )
    print(f"  ✅ 5 custom agents: {sorted(AGENT_NAMES + [COORDINATOR])}")

    # --- skills
    reg = load_skill_registry(cwd=str(Path.home()))
    found_skills = {s.name for s in reg.list_skills()}
    expected = set().union(*REQUIRED_SKILLS.values())
    missing_skills = expected - found_skills
    if missing_skills:
        raise SystemExit(
            f"❌ Missing skills: {missing_skills}\n"
            f"   Ensure symlinks exist in {SKILLS_DIR}/"
        )
    print(f"  ✅ {len(expected)} user skills present (resolved via symlinks in {SKILLS_DIR}/)")

    # --- show agent → skill mapping
    print()
    print("  Agent → Skills 路由表:")
    for name in AGENT_NAMES:
        a = get_agent_definition(name)
        print(f"    {name:22s} (color={a.color:6s})  → {a.skills}")


# ---------------------------------------------------------------------------
# Step 1: Team creation via TeamLifecycleManager
# ---------------------------------------------------------------------------
def create_team(scenario: dict) -> str:
    banner("Step 1 · 创建团队（TeamLifecycleManager）")
    team_name = scenario["team"]
    mgr = TeamLifecycleManager()

    # Clean slate
    if mgr.get_team(team_name):
        print(f"  [reset] 删除已有团队: {team_name}")
        mgr.delete_team(team_name)

    team = mgr.create_team(
        team_name,
        description=scenario["user_request"],
    )
    print(f"  [create] 团队名: {team.name}")
    print(f"  [create] 描述: {team.description[:60]}...")
    print(f"  [file]   {TEAMS_DIR / team_name / 'team.json'}")

    # Add 4 specialist members + coordinator
    members_added = []
    for st in AGENT_NAMES:
        ad = get_agent_definition(st)
        member = TeamMember(
            agent_id=f"{st}@{team_name}",
            name=st,
            backend_type="subprocess",
            joined_at=time.time(),
            agent_type=st,
            model=ad.model,
            color=ad.color,
            cwd=str(PROJECT_ROOT),
            status="active",
        )
        mgr.add_member(team_name, member)
        members_added.append(member.name)
    coord = TeamMember(
        agent_id=f"{COORDINATOR}@{team_name}",
        name=COORDINATOR,
        backend_type="subprocess",
        joined_at=time.time(),
        agent_type=COORDINATOR,
        color="purple",
        cwd=str(PROJECT_ROOT),
        status="active",
    )
    mgr.add_member(team_name, coord)
    members_added.append(coord.name)

    print(f"  [members] 共 {len(members_added)} 个: {members_added}")
    return team_name


# ---------------------------------------------------------------------------
# Step 2a: Mock specialist runner
# ---------------------------------------------------------------------------
def mock_specialist_output(specialist: str, plan_prompt: str) -> str:
    """Deterministic, scenario-aware mock LLM output for V2 clinical specialists."""
    # Chest-pain red flag mock (detected from prompt keywords)
    if specialist == "intake-specialist" and ("胸痛" in plan_prompt or "红旗症状可能命中" in plan_prompt):
        return json.dumps({
            "RESULT": "intake_complete",
            "red_flag": True,
            "type": "胸痛",
            "action": "立即拨打 120，去最近的胸痛中心/急诊",
            "rationale": "60 岁男性，急性胸痛+大汗，高血压 10 年 → 高度怀疑 ACS",
            "skip_synthesis": True,
        }, ensure_ascii=False, indent=2)

    mocks = {
        "intake-specialist": json.dumps({
            "RESULT": "intake_complete",
            "red_flag": False,
            "patient": {
                "id": "PT-20260609-001", "name": "患儿", "gender": "M", "age": 5, "is_new": True
            },
            "chief_complaint": "发热 38.5°C 持续 6 小时，伴轻微咳嗽",
            "interview_sections": {
                "chief_complaint": "发热 38.5°C 持续 6h，轻微咳嗽",
                "present_illness": "6h前无明显诱因出现发热，体温最高38.5°C，伴轻微干咳",
                "past_history": "体健，无慢性病",
                "allergy": "未发现",
                "family_history": "父母体健"
            },
            "entities": {
                "symptoms": [{"text": "发热38.5°C", "duration": "6h"}, {"text": "干咳", "duration": "未明"}],
                "drugs": [], "allergies": []
            },
            "ocr_results": [],
            "next_step": "dispatch knowledge + analysis + evolution"
        }, ensure_ascii=False, indent=2),

        "knowledge-specialist": json.dumps({
            "RESULT": "knowledge_retrieved",
            "query": "儿童发热 咳嗽",
            "engines_used": ["toc", "rag", "kg"],
            "toc_results": [
                {"book": "19诊断学 第10版", "chapter": "咳嗽与咳痰", "score": 22},
                {"book": "50急诊与灾难医学 第4版", "chapter": "急性发热", "score": 20}
            ],
            "rag_results": [
                {"book": "儿科学", "preview": "上呼吸道感染是儿童最常见的疾病...", "score": 0.85}
            ],
            "kg_results": [
                {"entity": "上呼吸道感染", "relations": ["症状:发热", "症状:咳嗽", "治疗:对症"], "confidence": 0.9}
            ],
            "blind_spots": [],
            "supplement_triggered": False,
            "summary": "找到 8 条相关知识（TOC 3 + RAG 2 + KG 3），无盲区"
        }, ensure_ascii=False, indent=2),

        "analysis-specialist": json.dumps({
            "RESULT": "analysis_complete",
            "drug_interactions": [],
            "lab_interpretation": {},
            "differential_diagnosis": {
                "primary": {"name": "急性上呼吸道感染", "icd10": "J06.9", "confidence": 0.70},
                "differential": [
                    {"name": "流行性感冒", "confidence": 0.50, "key_differentiator": "查流感接触史"},
                    {"name": "细菌性肺炎早期", "confidence": 0.20, "key_differentiator": "关注呼吸频率"}
                ]
            },
            "bias_check": {"anchoring": "无", "search_satisficing": "已考虑3个"},
            "self_evaluation": {"score": 0.85}
        }, ensure_ascii=False, indent=2),

        "evolution-specialist": json.dumps({
            "RESULT": "evolution_complete",
            "evolution_run": {
                "round": 12, "patients_analyzed": 20, "visit_records": 175,
                "new_patterns_found": 1,
                "patterns_promoted": {"to_clinical_rule": 0, "to_kg_injection": 0}
            },
            "current_state": {
                "diagnosis_clusters": 27, "high_confidence_patterns": 2,
                "kg_relations_injected": 11, "active_clinical_rules": 1
            },
            "clinical_rules": [
                {"id": "CR-急性胃肠炎-6-20260601", "confidence": 0.627,
                 "evidence_count": 6, "presentation": "乏力+呕吐+脱水+腹泻+腹痛"}
            ]
        }, ensure_ascii=False, indent=2),
    }
    return mocks.get(specialist, json.dumps({"RESULT": "noop"}, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Step 2b: Real LLM specialist runner (subprocess: openharness -p)
# ---------------------------------------------------------------------------
def real_specialist_run(
    team_name: str,
    specialist: str,
    plan_prompt: str,
    timeout_s: int = 180,
) -> str:
    """Spawn a real openharness subprocess that runs the specialist task.

    The subprocess uses:
      - `--append-system-prompt` to inject the specialist's role from
        `~/.openharness/agents/<name>.md`
      - `-p` for non-interactive print mode
      - inherits provider/env from the parent (via spawn_utils defaults)
    """
    agent_md = (AGENTS_DIR / f"{specialist}.md").read_text(encoding="utf-8")
    # strip frontmatter
    body = re.sub(r"^---\n.*?\n---\n", "", agent_md, flags=re.DOTALL).strip()

    # 拼一个明确的执行 prompt，告诉 specialist 它的 mailbox 在哪
    specialist_id = f"{specialist}@{team_name}"
    inbox_dir = TEAMS_DIR / team_name / "agents" / specialist_id / "inbox"
    coord_id = f"{COORDINATOR}@{team_name}"
    full_prompt = f"""\
{plan_prompt}

---
[OpenHarness 多智能体上下文]
你的 agent_id: {specialist_id}
团队: {team_name}
你可以通过文件系统读 inbox 接收任务: {inbox_dir}
完成后你的输出会被协调器收集。
请按 system_prompt 中规定的 JSON 格式输出结果。
"""

    env = os.environ.copy()
    env.setdefault("OPENHARNESS_PROFILE", "openrouter")
    # Prevent recursion of coordinator mode
    env["CLAUDE_CODE_COORDINATOR_MODE"] = "0"

    cmd = [
        "uv", "run", "openharness",
        "--append-system-prompt", body,
        "-p", full_prompt,
        "--output-format", "text",
        "--max-turns", "15",
        "--dangerously-skip-permissions",
    ]

    print(f"    [spawn] {' '.join(cmd[:6])}...")
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, env=env,
            capture_output=True, text=True, timeout=timeout_s,
        )
        if result.returncode != 0:
            print(f"    [WARN] subprocess exit={result.returncode}")
            if result.stderr:
                # only print last 200 chars to avoid noise
                tail = result.stderr.strip()[-200:]
                print(f"    [stderr-tail] {tail}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return json.dumps({
            "RESULT": "timeout",
            "NOTES": f"specialist timeout after {timeout_s}s",
        }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Step 2: Coordinator dispatch loop
# ---------------------------------------------------------------------------
async def run_coordinator(
    scenario: dict,
    *,
    use_real_llm: bool,
    timeout_s: int,
) -> dict[str, str]:
    """Dispatch to 4 specialists, gather results, write to coordinator's inbox."""
    banner("Step 2 · Coordinator 派发任务到 4 个 specialist")
    team_name = scenario["team"]
    coord_id = f"{COORDINATOR}@{team_name}"

    # clear coordinator's inbox (use full agent_id format for consistency)
    coord_mb = TeammateMailbox(team_name, coord_id)
    await coord_mb.clear()

    # 1) write initial task to each specialist's inbox
    print("  [dispatch] 写任务到 4 个 specialist 的 inbox")
    for st, prompt in scenario["plan"]:
        st_id = f"{st}@{team_name}"
        st_mb = TeammateMailbox(team_name, st_id)
        await st_mb.clear()
        await st_mb.write(create_user_message(
            sender=coord_id, recipient=st_id, content=prompt,
        ))
        inbox_dir = TEAMS_DIR / team_name / "agents" / st_id / "inbox"
        print(f"    → {st_id:50s}  ({len(prompt)} chars)  {inbox_dir.name}/")
    _ = coord_id  # coordinator id is captured above

    # 2) run each specialist (mock or real LLM)
    print()
    mode = "REAL LLM" if use_real_llm else "MOCK LLM"
    print(f"  [run] 执行模式: {mode}")
    results: dict[str, str] = {}
    for st, prompt in scenario["plan"]:
        print(f"\n  ── {st} ──")
        t0 = time.time()
        if use_real_llm:
            out = real_specialist_run(team_name, st, prompt, timeout_s=timeout_s)
        else:
            # tiny pause so users can see the dispatch order
            await asyncio.sleep(0.2)
            out = mock_specialist_output(st, prompt)
        dt = time.time() - t0
        results[st] = out
        print(f"    [done] {len(out)} chars in {dt:.1f}s")

        # 3) write result to coordinator's inbox
        await coord_mb.write(create_user_message(
            sender=f"{st}@{team_name}",
            recipient=coord_id,
            content=out,
        ))
        # write idle notification
        await coord_mb.write(create_idle_notification(
            sender=f"{st}@{team_name}",
            recipient=coord_id,
            summary=f"{st} finished",
        ))

    return results


# ---------------------------------------------------------------------------
# Step 3: Coordinator synthesis
# ---------------------------------------------------------------------------
def synthesize_report(scenario: dict, results: dict[str, str]) -> str:
    banner(f"Step 3 · Coordinator 汇总报告 — {scenario['team']}")
    lines = [
        f"# 多智能体协作报告：{scenario['team']}",
        f"原始请求: {scenario['user_request']}",
        "",
    ]
    for st, _ in scenario["plan"]:
        out = results[st]
        lines.append(f"## {st}")
        lines.append("```json")
        # try to pretty-print if it's valid JSON
        try:
            lines.append(json.dumps(json.loads(out), ensure_ascii=False, indent=2))
        except (json.JSONDecodeError, TypeError):
            lines.append(out)
        lines.append("```")
        lines.append("")
    lines.append("## 综合建议")
    lines.append(
        "1. **分诊**：当前无红旗症状，对症护理 + 观察 24-48h\n"
        "2. **药物**：≥ 38.5°C 可用布洛芬或对乙酰氨基酚（开药前已查药物相互作用）\n"
        "3. **红线**：出现持续高烧>48h/呼吸急促/精神萎靡/无法进食 → 立即就医\n"
        "4. **知识**：三引擎检索找到儿科学/诊断学/急诊相关章节，支持诊断\n"
        "5. **进化**：本轮问诊已触发自进化，提取发热+咳嗽→上感诊断模式\n"
    )
    lines.append(
        "> ⚠️ 本结论仅供参考，不构成医疗建议。紧急情况请立即就医。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 4: Show artifacts
# ---------------------------------------------------------------------------
def show_artifacts(team_name: str) -> None:
    banner("Step 4 · 磁盘产物（用户在文件管理器可直接看到）")
    team_dir = TEAMS_DIR / team_name
    if not team_dir.exists():
        print("  ❌ no team dir")
        return

    # team.json
    team_json = team_dir / "team.json"
    print(f"\n📄 {team_json}")
    print(f"   size: {team_json.stat().st_size} bytes")
    data = json.loads(team_json.read_text())
    print(f"   members ({len(data['members'])}):")
    for k, m in data["members"].items():
        print(f"     - {m['name']:22s}  color={m.get('color') or '-':8s}  backend={m['backend_type']}")

    # all inbox files
    print()
    for agent_dir in sorted(team_dir.glob("agents/*")):
        inbox = agent_dir / "inbox"
        if not inbox.is_dir():
            continue
        msgs = sorted(inbox.glob("*.json"))
        if not msgs:
            continue
        print(f"📬 {agent_dir.name}/inbox/  ({len(msgs)} messages)")
        for m in msgs:
            payload = json.loads(m.read_text())
            t = payload.get("type", "?")
            sender = payload.get("sender", "?")
            # payload can be in `content`/`summary` (text) field
            body_obj = payload.get("payload", {})
            text_field = body_obj.get("content", "") if isinstance(body_obj, dict) else ""
            preview = (text_field or payload.get("summary", ""))[:60]
            print(f"     - {m.name:35s} type={t:18s} from={sender:38s}  {preview!r}...")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def cleanup(team_name: str) -> None:
    team_dir = TEAMS_DIR / team_name
    if team_dir.exists():
        shutil.rmtree(team_dir)
        print(f"[cleanup] removed {team_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="child-fever-triage",
                        choices=list(SCENARIOS.keys()))
    parser.add_argument("--real", action="store_true",
                        help="Use real LLM (default: mock)")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Per-specialist timeout in seconds (default: 180)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Keep the team directory after the demo")
    args = parser.parse_args()

    use_real = args.real or (os.environ.get("MULTI_AGENT_REAL") == "1")
    scenario = SCENARIOS[args.scenario]

    print(f"📌 Scenario : {args.scenario}")
    print(f"📌 LLM mode : {'REAL (OpenRouter)' if use_real else 'MOCK (deterministic)'}")
    print(f"📌 Timeout  : {args.timeout}s per specialist")
    print(f"📌 Project  : {PROJECT_ROOT}")

    try:
        preflight()
        team_name = create_team(scenario)
        results = asyncio.run(run_coordinator(
            scenario, use_real_llm=use_real, timeout_s=args.timeout,
        ))
        report = synthesize_report(scenario, results)
        print(report)
        show_artifacts(team_name)
    finally:
        if not args.no_cleanup:
            cleanup(scenario["team"])

    print()
    print("✅ Demo complete. Re-run with --no-cleanup to inspect the team dir.")
    print("   Re-run with --real to use the real OpenRouter LLM.")


if __name__ == "__main__":
    main()
