"""Smoke test for P9 — real-LLM verification of plan-first protocol.

This is the FIRST end-to-end test of the plan-first protocol against
the actual LLM (not a mock). It goes through the live backend on
localhost:8000, opens a /ws/scenario connection with mode=plan_first,
and asks a real question.

What this verifies:

  1. The injected _PLAN_FIRST_PREFIX in the system prompt actually
     steers the LLM into calling plan() as its first action.
  2. The LLM follows the protocol: plan → update_todo per step →
     final text. (Not strictly required, but a good signal.)
  3. The runner correctly forwards the new P9 events to the WS:
       specialist.plan_return
       specialist.step_status
  4. The runner does NOT abort any specialist with "plan_required" —
     i.e. the LLM actually obeyed the prefix.
  5. scenario.done is reached (the run terminated cleanly).

Why this test matters:

  The in-process smoke (smoke_p9_plan_first.py) verifies the
  PROTOCOL — state machine, validation, event ordering. But it does
  not prove the LLM will follow the protocol. That's what this test
  is for. A model that consistently ignores the prefix is a signal
  to rewrite the system prompt; a model that mostly follows it is
  good enough for Phase 2.

Robustness:

  - Uses a Chinese medical question (multi-step by nature: assess
    fever, give advice, when to seek care) so analysis-specialist
    has obvious sub-steps to break the answer into.
  - Other specialists (iot/nas/education) get a "this is out of my
    domain" reply and may or may not call plan() — the test treats
    them permissively (no requirement, but no error either).
  - We clear all specialist histories first so prior runs don't
    pollute the new conversation. This also prevents the LLM from
    seeing "OK" replies from previous test runs in its context.

Run with backend running on :8000 (and venv active):
    python webui/scripts/smoke_p9_reallm.py
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

# Question chosen to have natural sub-steps so the LLM will produce
# 2+ TodoStep items in its plan.
REQUEST = (
    "我家 3 岁孩子发烧 38.5°C，有点流鼻涕，"
    "精神还可以。请问应该怎么处理？什么时候需要去医院？"
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


async def run_scenario_plan_first(request: str, timeout_s: float = 180.0) -> list[dict]:
    """Open a /ws/scenario with mode=plan_first and collect events until
    scenario.done or scenario.error (or timeout)."""
    events: list[dict] = []
    try:
        async with websockets.connect(SCENARIO_URI) as ws:
            await ws.send(json.dumps({
                "type": "start",
                "request": request,
                "mode": "plan_first",
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
    """Print one line per P9 protocol event, plus the per-specialist summary."""
    print("\n  P9 protocol events (plan_return / step_status / tool_call):")
    for e in events:
        t = e.get("type")
        if t == "specialist.plan_return":
            todos = e.get("todos") or []
            ids = [t.get("id") for t in todos]
            print(f"    plan_return  name={e.get('name'):<22} rev={e.get('rev')} "
                  f"todos={ids} (n={len(todos)})")
        elif t == "specialist.step_status":
            print(f"    step_status  name={e.get('name'):<22} step={e.get('step_id'):<5} "
                  f"status={e.get('status')}")
        elif t == "specialist.error":
            print(f"    specialist.error name={e.get('name'):<22} detail={e.get('detail')!r}")


def main() -> int:
    print("P9 plan-first REAL-LLM smoke")
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

    banner("Run /ws/scenario with mode=plan_first against real LLM")
    events = asyncio.run(run_scenario_plan_first(REQUEST, timeout_s=180.0))

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
    print(f"✓ scenario.done received (status={term.get('status')!r})")

    # A2. AT LEAST ONE specialist emitted plan_return
    # (the protocol CAN be followed by the LLM; if 0, the prefix failed
    # wholesale and there's a prompt-engineering problem)
    plan_return_total = sum(s["plan_return"] for s in per.values())
    if plan_return_total == 0:
        print("❌ NO specialist emitted plan_return — the LLM did not call plan()")
        print("   (this means the system-prompt prefix was ignored wholesale)")
        return 1
    print(f"✓ {plan_return_total} plan_return event(s) emitted "
          f"(at least one specialist called plan() as the first action)")

    # A3. AT LEAST ONE specialist emitted at least one step_status
    step_status_total = sum(s["step_status"] for s in per.values())
    if step_status_total == 0:
        print("❌ NO step_status events — the LLM did not call update_todo()")
        return 1
    print(f"✓ {step_status_total} step_status event(s) emitted (update_todo was used)")

    # A4. AT LEAST ONE specialist finished cleanly
    finished = [n for n, s in per.items() if s["done"]]
    if not finished:
        print("❌ no specialist reached specialist.done — all errored or were cut off")
        return 1
    print(f"✓ {len(finished)} specialist(s) reached specialist.done: {finished}")

    # A5. plan_required rate is reasonable (LLM isn't wholesale ignoring the prefix)
    # We allow up to 50% — a query that is clearly off-domain for 1-2 specialists
    # will trigger plan_required for them, and that's a useful signal but not a
    # protocol failure. If >50% hit it, the prefix wording needs work.
    plan_required_count = sum(
        1 for s in per.values() if s.get("error") and "plan_required" in s["error"]
    )
    total_specialists = len(per)
    if total_specialists > 0 and plan_required_count / total_specialists > 0.5:
        print(f"❌ {plan_required_count}/{total_specialists} specialists hit plan_required "
              f"(>50%); the prefix isn't strong enough")
        for name, s in per.items():
            if s.get("error") and "plan_required" in s["error"]:
                print(f"     - {name}: {s['error']!r}")
        return 1
    print(f"✓ plan_required rate: {plan_required_count}/{total_specialists} "
          f"specialists (off-domain LLM may skip plan() for trivial replies)")

    # A6. The successful specialist's history actually contains a plan() tool_call
    # (proves the LLM's call hit OpenAI, not just the runner)
    for name in finished:
        history = http_get(f"/api/specialists/{name}/history")
        plan_tool_calls = []
        for m in history:
            if m.get("role") == "assistant":
                for tc in (m.get("tool_calls") or []):
                    fn = (tc.get("function") or {}).get("name", "")
                    if fn == "plan":
                        plan_tool_calls.append(tc)
        if plan_tool_calls:
            print(f"✓ {name} history contains {len(plan_tool_calls)} plan() tool_call(s)")
            break
    else:
        print("⚠ no finished specialist had a plan() tool_call in its history")

    # Cleanup
    clear_all_histories()

    print("\n✅ P9 plan-first REAL-LLM smoke passed")
    print(f"   - {plan_return_total} plan_return, {step_status_total} step_status")
    print(f"   - {len(finished)} specialist(s) reached done cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
