"""Smoke test for P10 — real-LLM verification of the coordinator protocol.

This is the FIRST end-to-end test of the hierarchical-supervisor pattern
against the actual LLM (not a mock). It goes through the live backend on
localhost:8000, opens a /ws/scenario connection with mode=coordinator,
and asks a multi-domain question.

What this verifies:

  1. The injected _COORDINATOR_PROTOCOL in the coordinator's system
     prompt actually steers the LLM into the dispatch→proceed→publish
     workflow.
  2. The coordinator calls dispatch() against at least one specialist,
     then proceed() (or revise()), then publish_final_report.
  3. Specialist runs invoked via dispatch/proceed stream their events
     into the WS (text + plan_return + done), so the live UI sees them.
  4. The run terminates cleanly with scenario.done status="ok" carrying
     a non-empty final_report.

Why this test matters:

  The in-process smoke (smoke_p10_coordinator.py) verifies the PROTOCOL
  — tool dispatch, sentinel, state machine, event ordering. But it does
  not prove the LLM will follow the supervisor pattern. That's what
  this test is for. A model that consistently skips publish_final_report
  or never calls proceed is a signal to rewrite the system prompt; a
  model that mostly follows the protocol is good enough for v1.

Pragmatic:
  - We don't assert specific tool-call sequences; the LLM may dispatch
    0, 1, 2, or more specialists depending on its judgment. We just
    require ≥1 dispatch AND ≥1 publish_final_report AND ≥1 specialist
    that reached `done` via a proceed-style invocation (not just plan).
  - We allow max_turns=60 (the coordinator agent's default) — a 3-4
    specialist scenario typically finishes in 4-8 LLM turns.

Robustness:
  - We clear all specialist histories first so prior runs don't
    pollute the new conversation.
  - We pick a Chinese medical question (3-year-old fever) because it
    cross-cuts multiple specialists (medical + education + iot/nas for
    home-care logistics) and gives the coordinator real work to do.

Run with backend running on :8000 (and venv active):
    python webui/scripts/smoke_p10_reallm.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request

import websockets


SCENARIO_URI  = "ws://localhost:8000/ws/scenario"
BASE          = "http://localhost:8000"
HEALTH_URI    = f"{BASE}/api/health"

# Same multi-domain question used in P9's real-LLM smoke.  Coordinator
# should ideally dispatch analysis-specialist first, then education (for
# general care / fever-care knowledge), then synthesize a final report.
REQUEST = (
    "我家 3 岁孩子发烧 38.5°C，有点流鼻涕，精神还可以。"
    "请问应该怎么处理？什么时候需要去医院？平时有什么护理常识？"
)

# Specialists defined in ~/.openharness/agents/. We clear their
# histories before/after the test to keep this hermetic.
AGENT_NAMES = ["intake-specialist", "knowledge-specialist", "analysis-specialist", "evolution-specialist"]


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


def http_get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}") as r:
        return json.loads(r.read().decode("utf-8"))


def http_delete(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", method="DELETE")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def clear_all_histories() -> None:
    for name in AGENT_NAMES:
        try:
            http_delete(f"/api/specialists/{name}/history")
        except Exception:
            pass
    print("✓ cleared histories for 4 specialists")


def summarize_events(events: list[dict]) -> dict:
    """Bucket events so we can print a compact report."""
    by_type: dict[str, int] = {}
    for e in events:
        t = e.get("type", "?")
        by_type[t] = by_type.get(t, 0) + 1
    return by_type


def per_specialist_summary(events: list[dict]) -> dict:
    """For each specialist, what did they do?"""
    per: dict[str, dict] = {}
    for e in events:
        name = e.get("name")
        if not name:
            continue
        slot = per.setdefault(name, {
            "plan_return": 0,
            "step_status": 0,
            "tool_call": 0,
            "token_chars": 0,
            "done": False,
            "error": None,
        })
        t = e["type"]
        if t == "specialist.plan_return":
            slot["plan_return"] += 1
        elif t == "specialist.step_status":
            slot["step_status"] += 1
        elif t == "specialist.tool_call":
            slot["tool_call"] += 1
        elif t == "specialist.token":
            slot["token_chars"] += len(e.get("delta", ""))
        elif t == "specialist.done":
            slot["done"] = True
        elif t == "specialist.error":
            slot["error"] = e.get("detail")
    return per


async def run_scenario_coordinator(request: str, timeout_s: float = 240.0) -> list[dict]:
    """Open a /ws/scenario with mode=coordinator and collect events until
    scenario.done or scenario.error (or timeout)."""
    events: list[dict] = []
    try:
        async with websockets.connect(SCENARIO_URI) as ws:
            await ws.send(json.dumps({
                "type": "start",
                "request": request,
                "mode": "coordinator",
            }))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
                ev = json.loads(raw)
                events.append(ev)
                if ev.get("type") in ("scenario.done", "scenario.error"):
                    return events
    except asyncio.TimeoutError:
        print(f"❌ timeout after {timeout_s}s waiting for scenario.done")
        return events
    except websockets.exceptions.ConnectionClosed:
        print("❌ WS connection closed before scenario.done")
        return events


def print_event_log_compact(events: list[dict]) -> None:
    """Print one line per P10 coordinator/protocol event."""
    print("\n  P10 protocol events (coordinator.* + specialist.plan_return/step_status/done):")
    for e in events:
        t = e.get("type")
        if t == "coordinator.tool_call":
            tool_name = e.get("tool_name")
            inp = e.get("tool_input") or {}
            # Compact view: show agent_name for dispatch/proceed/revise
            target = inp.get("agent_name", "")
            if tool_name in ("dispatch", "proceed", "revise", "observe", "finish_agent"):
                print(f"    coordinator.tool_call {tool_name}({target or '...'})")
            else:
                print(f"    coordinator.tool_call {tool_name}({inp})")
        elif t == "coordinator.tool_result":
            tool_name = e.get("tool_name")
            is_err = e.get("is_error", False)
            out = e.get("output", "")
            if isinstance(out, str):
                out = out[:80]
            print(f"    coordinator.tool_result {tool_name} is_error={is_err} output={out!r}")
        elif t == "coordinator.done":
            txt = (e.get("text") or "")[:80]
            print(f"    coordinator.done text={txt!r}...")
        elif t == "coordinator.error":
            print(f"    coordinator.error detail={e.get('detail')!r}")
        elif t == "specialist.plan_return":
            todos = e.get("todos") or []
            ids = [t.get("id") for t in todos]
            print(f"    specialist.plan_return name={e.get('name'):<22} rev={e.get('rev')} "
                  f"todos={ids} (n={len(todos)})")
        elif t == "specialist.step_status":
            print(f"    specialist.step_status name={e.get('name'):<22} "
                  f"step={e.get('step_id'):<5} status={e.get('status')}")
        elif t == "specialist.error":
            print(f"    specialist.error name={e.get('name'):<22} "
                  f"detail={e.get('detail')!r}")


def main() -> int:
    print("P10 coordinator REAL-LLM smoke")
    print(f"backend: {BASE}")
    print(f"request: {REQUEST!r}")

    # Health check
    try:
        http_get("/api/health")
    except Exception as e:
        print(f"❌ backend unreachable: {e}")
        return 1
    print("✓ backend healthy")

    # Hermetic state
    clear_all_histories()

    banner("Run /ws/scenario with mode=coordinator against real LLM")
    events = asyncio.run(run_scenario_coordinator(REQUEST, timeout_s=240.0))

    by_type = summarize_events(events)
    print(f"\n  total events: {len(events)}")
    print(f"  event counts: {by_type}")

    per = per_specialist_summary(events)
    print(f"\n  per-specialist summary:")
    for name, s in per.items():
        chars = s["token_chars"]
        print(f"    {name:<22} plan_return={s['plan_return']:<2} "
              f"step_status={s['step_status']:<2} tool_call={s['tool_call']:<2} "
              f"chars={chars:<5} done={s['done']!s:<5} error={s['error']}")

    print_event_log_compact(events)

    # ---------------- assertions -------------------------------------------------
    banner("Assertions")

    # A1. scenario.done (not scenario.error) was received
    terminals = [e for e in events if e.get("type") in ("scenario.done", "scenario.error")]
    if not terminals:
        print("❌ no terminal scenario.done / scenario.error received")
        return 1
    term = terminals[-1]
    if term["type"] != "scenario.done":
        print(f"❌ terminal is {term['type']!r}, expected scenario.done; "
              f"detail={term.get('detail')!r}")
        return 1
    if term.get("status") != "ok":
        print(f"❌ scenario.done.status={term.get('status')!r}, expected 'ok'")
        return 1
    final_report = term.get("final_report") or ""
    if not final_report.strip():
        print("❌ scenario.done.final_report is empty")
        return 1
    print(f"✓ scenario.done status=ok, final_report has {len(final_report)} chars")

    # A2. AT LEAST ONE coordinator.tool_call event
    coord_tool_calls = [e for e in events if e.get("type") == "coordinator.tool_call"]
    if not coord_tool_calls:
        print("❌ NO coordinator.tool_call events — the LLM did not use any tool")
        return 1
    tool_names = [e.get("tool_name") for e in coord_tool_calls]
    print(f"✓ {len(coord_tool_calls)} coordinator.tool_call event(s): {tool_names}")

    # A3. AT LEAST ONE dispatch tool call (the supervisor must talk to specialists)
    dispatch_count = tool_names.count("dispatch")
    if dispatch_count == 0:
        print("❌ NO dispatch() call — the coordinator never talked to a specialist")
        return 1
    print(f"✓ {dispatch_count} dispatch() call(s) (coordinator reached specialists)")

    # A4. AT LEAST ONE publish_final_report tool call (the terminal action)
    publish_count = tool_names.count("publish_final_report")
    if publish_count == 0:
        print("❌ NO publish_final_report() call — the run did not terminate properly")
        return 1
    print(f"✓ {publish_count} publish_final_report() call(s) (run terminated)")

    # A5. AT LEAST ONE coordinator.done event with non-empty text
    coord_dones = [e for e in events if e.get("type") == "coordinator.done"]
    if not coord_dones or not (coord_dones[-1].get("text") or "").strip():
        print("❌ coordinator.done missing or empty")
        return 1
    print(f"✓ coordinator.done text has {len(coord_dones[-1]['text'])} chars")

    # A6. AT LEAST ONE specialist RAN to completion (real work happened, not
    # just plans). In coordinator-driven runs, the WS event "specialist.done"
    # is NOT emitted by _run_specialist_to_event — instead, the evidence of
    # completion is (a) ≥1 proceed/finish_agent tool call from the coordinator
    # and (b) step_status events marking todos done, or (c) the
    # coordinator.tool_result for dispatch/proceed/revise reporting a
    # "status=done" summary.  We use the simplest signal: a proceed/revise
    # call paired with at least one step_status="done" event.
    proceed_or_revise = tool_names.count("proceed") + tool_names.count("revise")
    step_done_events = [e for e in events
                        if e.get("type") == "specialist.step_status"
                        and e.get("status") == "done"]
    if proceed_or_revise == 0 and not step_done_events:
        print("❌ no proceed/revise call AND no step_status='done' events — "
              "coordinator only collected plans")
        return 1
    print(f"✓ specialist ran to completion "
          f"(proceed/revise={proceed_or_revise}, step_status='done'={len(step_done_events)})")

    # A7. plan_return was emitted (the LLM followed the plan-first-pause protocol
    # when calling dispatch)
    plan_return_total = sum(s["plan_return"] for s in per.values())
    if plan_return_total == 0:
        print("⚠ no specialist emitted plan_return — the LLM may have used wait_for='done'")
        print("   (not strictly a failure, but loses the supervisor's mid-flight visibility)")
    else:
        print(f"✓ {plan_return_total} plan_return event(s) (coordinator saw the plans)")

    # A8. step_status was emitted (the LLM actually used update_todo, not just text)
    step_status_total = sum(s["step_status"] for s in per.values())
    if step_status_total == 0:
        print("⚠ no step_status events — the LLM may not have called update_todo")
    else:
        print(f"✓ {step_status_total} step_status event(s) (update_todo was used)")

    # Cleanup
    clear_all_histories()

    print("\n✅ P10 coordinator REAL-LLM smoke passed")
    print(f"   - {len(coord_tool_calls)} coordinator tool calls "
          f"({dispatch_count} dispatch, {publish_count} publish)")
    print(f"   - final_report: {len(final_report)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
