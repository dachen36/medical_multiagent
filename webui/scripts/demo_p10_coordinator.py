"""P10 协调者模式 —— 现场演示 (narrator mode).

这个脚本不是过/不过的冒烟测试，而是一个"边跑边讲"的演示器。
目标是把 hierarchical supervisor 模式相比 P3.4 fan-out 强在哪
可视化出来：

  ┌─ 协调者 LLM（决策者） ─────────────────────────────────┐
  │ 看到 4 个 specialist 计划 → 选 1-2 个 → 派任务       │
  │ observe 微调 → proceed 跑 → assert → publish          │
  └────────────────────────────────────────────────────────┘
       │ dispatch  │ observe  │ proceed  │ publish
       ▼           ▼          ▼          ▼
  ┌─ specialist LLM（执行者，被串行调度） ────────────────┐
  │ plan(todos) → [revise?] → 边跑边 update_todo → done  │
  └────────────────────────────────────────────────────────┘

我们会看到：
  T+0.0s  用户问了一个跨域问题
  T+1.2s  协调者 LLM 第一轮：决定先派 medical
  T+2.4s  dispatch(medical, "评估...", wait_for="plan")
  T+8.7s  medical 返回 plan（3 个 todos）
  T+9.0s  协调者 LLM 第二轮：看 plan，决定 proceed
  T+9.1s  proceed(medical)
  T+9.1-25s  medical 边跑边 update_todo
  T+25.3s 协调者第三轮：可能再派 education
  T+...   assert_goal_coverage 自我确认
  T+...   publish_final_report 终止

最终把 final_report 完整打印出来。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.request

import websockets


SCENARIO_URI = "ws://localhost:8000/ws/scenario"
BASE         = "http://localhost:8000"
AGENT_NAMES  = ["intake-specialist", "knowledge-specialist", "analysis-specialist", "evolution-specialist"]

# 一个明确需要"先医学分诊、再教育科普"的跨域问题。协调者必须做决策
# 而不是并行 4 个 specialist —— 因为"什么时候要去医院"是 medical
# 的领地，"护理常识"才适合 education。
REQUEST = (
    "我家 3 岁孩子发烧 38.5°C，有点流鼻涕，精神还可以。"
    "请问应该怎么处理？什么时候需要去医院？"
    "平时在家有什么护理常识可以教家长？"
)


# ────────────────────── 工具函数 ────────────────────────────────────

def t_start() -> float:
    return time.monotonic()


def t_mark(t0: float) -> str:
    """返回自 t0 以来经过的时间，格式 +12.34s"""
    return f"+{time.monotonic() - t0:6.2f}s"


def http_get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}") as r:
        return json.loads(r.read().decode("utf-8"))


def http_delete(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", method="DELETE")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def clear_histories() -> None:
    for name in AGENT_NAMES:
        try:
            http_delete(f"/api/specialists/{name}/history")
        except Exception:
            pass


def short(text: str | None, n: int = 70) -> str:
    if not text:
        return ""
    s = str(text).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


# ────────────────────── 事件叙述器 ───────────────────────────────────

COORD_ICONS = {
    "dispatch":   "📤",
    "observe":    "🔍",
    "proceed":    "▶️ ",
    "revise":     "✏️ ",
    "finish_agent": "🛑",
    "assert_goal_coverage": "✅",
    "publish_final_report": "📜",
}


def narrate_coordinator_tool_call(t0: float, ev: dict) -> str:
    t = t_mark(t0)
    tool = ev.get("tool_name", "?")
    icon = COORD_ICONS.get(tool, "🔧")
    inp = ev.get("tool_input") or {}
    if tool == "dispatch":
        target = inp.get("agent_name", "?")
        wait   = inp.get("wait_for", "?")
        task   = short(inp.get("task", ""), 50)
        return f"{t} {icon} 协调者 → dispatch({target}, wait_for={wait!r})\n         任务：{task}"
    if tool == "proceed":
        return f"{t} {icon} 协调者 → proceed({inp.get('agent_name', '?')})"
    if tool == "revise":
        new_todos = inp.get("new_todos") or []
        return f"{t} {icon} 协调者 → revise({inp.get('agent_name', '?')}, new_todos={len(new_todos)} 项)"
    if tool == "observe":
        return f"{t} {icon} 协调者 → observe({inp.get('agent_name', '?')})"
    if tool == "finish_agent":
        return f"{t} {icon} 协调者 → finish_agent({inp.get('agent_name', '?')}, reason={inp.get('reason', '?')!r})"
    if tool == "assert_goal_coverage":
        conf = inp.get("confident")
        criteria = short(inp.get("criteria", ""), 60)
        marker = "✓" if conf else "✗"
        return f"{t} {icon} 协调者 → assert_goal_coverage(confident={marker})\n         准则：{criteria}"
    if tool == "publish_final_report":
        return f"{t} {icon} 协调者 → publish_final_report(text=…)  ← 终止信号"
    return f"{t} {icon} 协调者 → {tool}({inp})"


def narrate_coordinator_tool_result(t0: float, ev: dict) -> str:
    t = t_mark(t0)
    tool = ev.get("tool_name", "?")
    is_err = ev.get("is_error", False)
    out = ev.get("output", "")
    if not isinstance(out, str):
        out = json.dumps(out, ensure_ascii=False)
    marker = "❌" if is_err else "↩️ "
    return f"{t} {marker} {tool} 返回：{short(out, 90)}"


def narrate_specialist_plan_return(t0: float, ev: dict) -> str:
    t = t_mark(t0)
    name = ev.get("name", "?")
    rev = ev.get("rev", 0)
    todos = ev.get("todos") or []
    todo_lines = "\n".join(f"           - [{td.get('id', '?')}] {short(td.get('content', ''), 60)}"
                            for td in todos[:5])
    if len(todos) > 5:
        todo_lines += f"\n           … (共 {len(todos)} 项)"
    return (f"{t} 📋 {name} 返回 plan (rev={rev}, {len(todos)} todos):\n{todo_lines}")


def narrate_specialist_step_status(t0: float, ev: dict) -> str:
    t = t_mark(t0)
    name = ev.get("name", "?")
    step = ev.get("step_id", "?")
    status = ev.get("status", "?")
    icon = {"running": "⚙️ ", "done": "✓", "error": "✗"}.get(status, "·")
    return f"{t}    {icon}  {name}: step[{step}] → {status}"


# ────────────────────── 主流程 ──────────────────────────────────────

async def run_demo() -> int:
    print("=" * 78)
    print("  P10 协调者模式 现场演示")
    print("=" * 78)
    print(f"\n用户问题：\n  {REQUEST}\n")

    try:
        http_get("/api/health")
    except Exception as e:
        print(f"❌ 后端不通：{e}")
        return 1
    print("✓ 后端健康 (localhost:8000)")

    clear_histories()
    print("✓ 已清理 4 个 specialist 的历史（保证本次是干净启动）\n")

    print("-" * 78)
    print("▶ 启动协调者模式 …")
    print("-" * 78)

    events: list[dict] = []
    final_report = ""
    terminal_status = None

    t0 = t_start()
    try:
        async with websockets.connect(SCENARIO_URI) as ws:
            await ws.send(json.dumps({
                "type": "start",
                "request": REQUEST,
                "mode":   "coordinator",
            }))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=300.0)
                ev = json.loads(raw)
                events.append(ev)
                t = ev.get("type", "")

                if t == "coordinator.start":
                    print(f"\n{t_mark(t0)} ┌─ 协调者开始工作 ─────────────────────────")
                elif t == "coordinator.token":
                    sys.stdout.write(ev.get("delta", ""))
                    sys.stdout.flush()
                elif t == "coordinator.tool_call":
                    print()
                    print(narrate_coordinator_tool_call(t0, ev))
                elif t == "coordinator.tool_result":
                    print(narrate_coordinator_tool_result(t0, ev))
                elif t == "coordinator.done":
                    print(f"\n{t_mark(t0)} └─ 协调者文本流结束 "
                          f"({len(ev.get('text', ''))} chars)")
                elif t == "specialist.plan_return":
                    print(narrate_specialist_plan_return(t0, ev))
                elif t == "specialist.step_status":
                    print(narrate_specialist_step_status(t0, ev))
                elif t == "coordinator.error":
                    print(f"\n{t_mark(t0)} ❌ 协调者出错：{ev.get('detail')}")
                elif t == "scenario.done":
                    terminal_status = ev.get("status")
                    final_report = ev.get("final_report", "")
                    print(f"\n{t_mark(t0)} 🏁 scenario.done status={terminal_status!r} "
                          f"final_report={len(final_report)} chars")
                    break
                elif t == "scenario.error":
                    terminal_status = "error"
                    print(f"\n{t_mark(t0)} ❌ scenario.error detail={ev.get('detail')!r}")
                    break
    except asyncio.TimeoutError:
        print(f"\n❌ 300s 内没收到 terminal event")
        return 1
    except websockets.exceptions.ConnectionClosed as e:
        print(f"\n❌ WS 关闭：{e}")
        return 1

    # ───── 总结 ─────
    print("\n" + "=" * 78)
    print("  📊 这次跑出来的统计")
    print("=" * 78)

    coord_tools = [e for e in events if e.get("type") == "coordinator.tool_call"]
    by_tool: dict[str, int] = {}
    for e in coord_tools:
        n = e.get("tool_name", "?")
        by_tool[n] = by_tool.get(n, 0) + 1
    print(f"\n协调者一共做了 {len(coord_tools)} 次工具调用：")
    for name, cnt in sorted(by_tool.items(), key=lambda x: -x[1]):
        icon = COORD_ICONS.get(name, "·")
        print(f"  {icon} {name:<24} ×{cnt}")

    # 协调者实际"调度"了哪些 specialist
    dispatched = [e for e in coord_tools if e.get("tool_name") == "dispatch"]
    targets = []
    for e in dispatched:
        inp = e.get("tool_input") or {}
        if inp.get("agent_name"):
            targets.append(inp["agent_name"])
    print(f"\n协调者串行调度了 {len(targets)} 个 specialist：")
    for i, t in enumerate(targets, 1):
        print(f"  {i}. {t}")

    # 每个 specialist 实际跑了多少 step
    print(f"\n每个 specialist 的活跃度：")
    per: dict[str, dict] = {}
    for e in events:
        if e.get("type") == "specialist.step_status":
            n = e.get("name", "?")
            slot = per.setdefault(n, {"done": 0, "running": 0, "error": 0})
            s = e.get("status", "?")
            slot[s] = slot.get(s, 0) + 1
    for name in AGENT_NAMES:
        slot = per.get(name)
        if not slot:
            continue
        total = sum(slot.values())
        print(f"  {name:<22} {total} 个 step_update "
              f"(done={slot.get('done',0)}, running={slot.get('running',0)}, error={slot.get('error',0)})")

    # plan_return 数 vs publish 数
    plan_returns = sum(1 for e in events if e.get("type") == "specialist.plan_return")
    publishes    = by_tool.get("publish_final_report", 0)
    asserts      = by_tool.get("assert_goal_coverage", 0)
    print(f"\n工作流闭环：")
    print(f"  dispatch 调用           ×{len(dispatched)}")
    print(f"  plan_return 事件        ×{plan_returns}  (协调者看到的 plan 数)")
    print(f"  assert_goal_coverage    ×{asserts}       (显式确认关卡)")
    print(f"  publish_final_report    ×{publishes}      (终止信号)")

    # ───── 最终报告 ─────
    print("\n" + "=" * 78)
    print("  📜 协调者发布的最终报告 (final_report)")
    print("=" * 78)
    if final_report:
        print()
        for line in final_report.splitlines():
            print(f"  {line}")
    else:
        print("\n  (空)")

    clear_histories()
    return 0 if terminal_status == "ok" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_demo()))
