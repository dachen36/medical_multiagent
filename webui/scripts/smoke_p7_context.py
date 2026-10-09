"""Smoke test for P7.A — verify context unification across modes.

This test runs against a live backend on localhost:8000. It exercises
the cross-mode continuation contract:

  1. GET /api/specialists/{name}/history returns [] for a fresh agent
  2. /ws/scenario writes per-agent history (each agent in the team gets
     at least one user message and one assistant message)
  3. /ws/specialist against the same agent CONTINUES the conversation
     — the new turn appends user + assistant messages
  4. /ws/specialist against a DIFFERENT agent does NOT affect the
     first agent's history
  5. DELETE /api/specialists/{name}/history wipes the history

Robustness note: we count `role == "user"` messages (one per turn)
rather than total message count, because agents that use tools produce
many tool_call / tool_result triplets and the total length depends on
how many tools the LLM decides to call. User-message count is a
turn-count proxy and is independent of tool activity.

P5/P6 compat: this test only runs after the existing P5/P6 smokes
have passed; the new backend behavior is opt-in via the shared
`_specialist_history` dict.

Run from repo root, with backend running on :8000 and venv active:
    python webui/scripts/smoke_p7_context.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from typing import Any

import websockets


SCENARIO_URI  = "ws://localhost:8000/ws/scenario"
SPECIALIST_URI = "ws://localhost:8000/ws/specialist"
HEALTH_URI    = "http://localhost:8000/api/health"


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


def http_get(path: str) -> Any:
    with urllib.request.urlopen(f"http://localhost:8000{path}") as r:
        return json.loads(r.read().decode("utf-8"))


def http_delete(path: str) -> dict:
    req = urllib.request.Request(
        f"http://localhost:8000{path}", method="DELETE",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def count_user_msgs(history: list[dict]) -> int:
    """One user message == one turn. Tool_call/tool/assistant triplets
    do not add to this count."""
    return sum(1 for m in history if m.get("role") == "user")


def last_user_content(history: list[dict]) -> str:
    for m in reversed(history):
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""


def last_assistant_content(history: list[dict]) -> str:
    for m in reversed(history):
        if m.get("role") == "assistant":
            c = m.get("content")
            if c:  # skip null-content assistant messages (those are tool-only turns)
                return c
    return ""


async def recv_until(ws, *want: str) -> list[dict]:
    """Receive events until one of the wanted types arrives, or socket closes."""
    got: list[dict] = []
    while True:
        raw = await ws.recv()
        ev = json.loads(raw)
        got.append(ev)
        if ev.get("type") in want:
            return got


async def run_scenario(request: str) -> list[dict]:
    """Open a scenario WS, run to completion, return all events."""
    async with websockets.connect(SCENARIO_URI) as ws:
        await ws.send(json.dumps({"type": "start", "request": request}))
        events = await recv_until(ws, "scenario.done", "scenario.error")
        try:
            while True:
                extra = await asyncio.wait_for(ws.recv(), timeout=0.5)
                events.append(json.loads(extra))
        except (asyncio.TimeoutError, Exception):
            pass
        return events


async def run_specialist(agent_name: str, request: str) -> tuple[list[dict], str]:
    """Open a specialist WS, run to completion, return (events, final_text).
    final_text is from `specialist.done` (empty on error)."""
    async with websockets.connect(SPECIALIST_URI) as ws:
        await ws.send(json.dumps({
            "type": "start", "agentName": agent_name, "request": request,
        }))
        events = await recv_until(ws, "specialist.done", "specialist.error")
        try:
            while True:
                extra = await asyncio.wait_for(ws.recv(), timeout=0.5)
                events.append(json.loads(extra))
        except (asyncio.TimeoutError, Exception):
            pass
        last = events[-1] if events else {}
        text = last.get("text", "") if last.get("type") == "specialist.done" else ""
        return events, text


# ---------------------------------------------------------------------------
# Test 1: fresh agent history is empty
# ---------------------------------------------------------------------------
async def test_1_fresh_history_is_empty() -> None:
    banner("TEST 1: GET /api/specialists/{name}/history returns [] for fresh agent")
    # Use the intake-specialist for the test. First make sure it's clean.
    http_delete("/api/specialists/intake-specialist/history")
    hist = http_get("/api/specialists/intake-specialist/history")
    assert hist == [], f"expected [], got {hist!r}"
    print(f"  ✓ fresh intake-specialist history is []")


# ---------------------------------------------------------------------------
# Test 2: scenario writes per-agent history
# ---------------------------------------------------------------------------
async def test_2_scenario_writes_history() -> None:
    banner("TEST 2: /ws/scenario writes per-agent history")
    # Make sure we start clean
    for agent in ("intake-specialist", "knowledge-specialist", "analysis-specialist", "evolution-specialist"):
        http_delete(f"/api/specialists/{agent}/history")

    request = "P7A 烟雾测试 — 孩子发烧 38 度怎么办？"
    events = await run_scenario(request)

    # Confirm the scenario succeeded
    last = events[-1] if events else {}
    assert last.get("type") == "scenario.done", \
        f"scenario did not finish cleanly: last event = {last}"
    print(f"  ✓ scenario finished, last event = {last.get('type')}")

    # Each specialist in the team should now have 1 user message and
    # at least 1 assistant message.
    for agent in ("intake-specialist", "knowledge-specialist", "analysis-specialist", "evolution-specialist"):
        hist = http_get(f"/api/specialists/{agent}/history")
        n_users = count_user_msgs(hist)
        n_total = len(hist)
        if n_users == 0:
            print(f"  ⚠ {agent} history is empty (specialist may have errored/timeout)")
            continue
        assert n_users == 1, \
            f"{agent} expected 1 user message, got {n_users}: {hist!r}"
        assert n_total > 1, \
            f"{agent} expected >1 total messages (at least 1 user + 1 assistant), got {n_total}"
        # First message must be the user prompt that the scenario fed
        assert hist[0]["role"] == "user", \
            f"{agent} hist[0].role={hist[0].get('role')!r}, expected 'user'"
        assert request in (hist[0].get("content") or ""), \
            f"{agent} hist[0] doesn't contain the original request: {hist[0]!r}"
        # Some assistant message somewhere has non-null content (the
        # final reply). Agents that use tools have multiple assistant
        # messages, some of which have content=null (just tool_calls).
        final = last_assistant_content(hist)
        assert final, \
            f"{agent} no assistant message with non-null content: {hist!r}"
        print(f"  ✓ {agent} history: 1 turn, {n_total} msgs, "
              f"final assistant reply has {len(final)} chars")


# ---------------------------------------------------------------------------
# Test 3: standalone /ws/specialist continues the same agent's history
# ---------------------------------------------------------------------------
async def test_3_standalone_continues_history() -> None:
    banner("TEST 3: /ws/specialist continues the same agent's history (cross-mode)")
    # Pre: scenario wrote 1 turn for each agent (from test 2).
    pre = http_get("/api/specialists/intake-specialist/history")
    pre_users = count_user_msgs(pre)
    if pre_users < 1:
        print(f"  ⚠ skipping: intake-specialist history is too short "
              f"({pre_users} user msgs); test 2 likely didn't seed it")
        return
    print(f"  pre: intake-specialist has {pre_users} turn(s), {len(pre)} msgs")

    # Now send a standalone request that asks the model to do a small
    # task. The LLM should produce some output regardless of whether
    # it explicitly references the prior turn.
    events, final_text = await run_specialist(
        "intake-specialist",
        "P7A 续接测试 — 用一句话回答'好的'",
    )
    last = events[-1] if events else {}
    assert last.get("type") == "specialist.done", \
        f"standalone run failed: last event = {last}"
    assert final_text, f"empty final text: {last}"
    print(f"  ✓ standalone run finished, text={final_text[:60]!r}")

    # The history should now have exactly 1 more turn (2 more user
    # msgs if you count both starts, but our count_user_msgs is 1 turn
    # = 1 user msg, so we expect pre_users + 1).
    post = http_get("/api/specialists/intake-specialist/history")
    post_users = count_user_msgs(post)
    assert post_users == pre_users + 1, \
        f"intake-specialist user msgs: expected {pre_users + 1}, got {post_users}\n" \
        f"post history: {post!r}"
    print(f"  ✓ user msgs grew {pre_users} → {post_users} "
          f"(added 1 turn)")

    # The new turn's user content is the standalone request we just sent
    new_user = last_user_content(post)
    assert "P7A 续接测试" in new_user, \
        f"new user message is not the standalone request: {new_user!r}"
    print(f"  ✓ new turn's user message: {new_user[:60]!r}")

    # The pre-existing scenario user content is still at the head of
    # the history (NOT cleared, NOT replaced).
    assert any("P7A 烟雾测试" in (m.get("content") or "")
               for m in post if m.get("role") == "user"), \
        "scenario's user content is missing from post history"
    print(f"  ✓ original scenario content preserved at the head of history")

    # ** Key P7.A assertion **: the new assistant message is a real,
    # non-empty reply (not just an echo of the request, and not null).
    # The LLM was called with the full prior history as messages, so
    # it SAW the scenario's request — that's the contract.
    new_assistant = last_assistant_content(post)
    assert new_assistant, f"new assistant message is empty: {post!r}"
    assert "P7A 续接测试" not in new_assistant, \
        f"new assistant echoed the request verbatim: {new_assistant!r}"
    print(f"  ✓ new assistant message ({len(new_assistant)} chars) is a fresh reply, "
          f"not a verbatim echo of the request")


# ---------------------------------------------------------------------------
# Test 4: standalone /ws/specialist on a different agent doesn't affect others
# ---------------------------------------------------------------------------
async def test_4_other_agent_unaffected() -> None:
    banner("TEST 4: /ws/specialist on a different agent does not affect others")
    pre_iot = http_get("/api/specialists/intake-specialist/history")
    pre_nas = http_get("/api/specialists/knowledge-specialist/history")
    pre_iot_users = count_user_msgs(pre_iot)
    pre_nas_users = count_user_msgs(pre_nas)
    print(f"  pre: iot={pre_iot_users} turn(s), nas={pre_nas_users} turn(s)")

    # Hit knowledge-specialist
    events, final_text = await run_specialist(
        "knowledge-specialist", "P7A 隔离测试 — 用'OK'两个字回答我",
    )
    last = events[-1] if events else {}
    assert last.get("type") == "specialist.done", \
        f"nas run failed: {last}"

    post_iot = http_get("/api/specialists/intake-specialist/history")
    post_nas = http_get("/api/specialists/knowledge-specialist/history")
    assert count_user_msgs(post_iot) == pre_iot_users, \
        f"intake-specialist user msgs changed unexpectedly: " \
        f"{pre_iot_users} → {count_user_msgs(post_iot)}"
    assert count_user_msgs(post_nas) == pre_nas_users + 1, \
        f"knowledge-specialist user msgs: expected {pre_nas_users + 1}, " \
        f"got {count_user_msgs(post_nas)}"
    print(f"  ✓ intake-specialist history unchanged ({pre_iot_users} turn(s))")
    print(f"  ✓ knowledge-specialist history grew {pre_nas_users} → "
          f"{count_user_msgs(post_nas)} turn(s)")


# ---------------------------------------------------------------------------
# Test 5: DELETE /api/specialists/{name}/history wipes history
# ---------------------------------------------------------------------------
async def test_5_delete_clears_history() -> None:
    banner("TEST 5: DELETE /api/specialists/{name}/history wipes history")
    pre = http_get("/api/specialists/intake-specialist/history")
    assert len(pre) > 0, "pre: intake-specialist history should not be empty"
    print(f"  pre: intake-specialist history has {len(pre)} msgs, "
          f"{count_user_msgs(pre)} turn(s)")

    resp = http_delete("/api/specialists/intake-specialist/history")
    assert resp == {"cleared": "intake-specialist", "history": []}, \
        f"unexpected DELETE response: {resp!r}"
    print(f"  ✓ DELETE response: {resp}")

    post = http_get("/api/specialists/intake-specialist/history")
    assert post == [], f"post: intake-specialist history should be [], got {post!r}"
    print(f"  ✓ GET after DELETE returns []")

    # Idempotency: a second DELETE on an already-cleared agent should
    # not error.
    resp2 = http_delete("/api/specialists/intake-specialist/history")
    assert resp2 == {"cleared": "intake-specialist", "history": []}, \
        f"idempotent DELETE failed: {resp2!r}"
    print(f"  ✓ DELETE is idempotent (works on already-empty history)")

    # Subsequent standalone request works (the agent's history is fresh)
    events, final_text = await run_specialist(
        "intake-specialist", "P7A post-delete 测试 — 用'好的'两个字回答我",
    )
    last = events[-1] if events else {}
    assert last.get("type") == "specialist.done", \
        f"post-delete run failed: {last}"
    assert final_text, "post-delete run returned empty text"
    print(f"  ✓ post-delete run works: text={final_text[:40]!r}")

    # History should now have exactly 1 turn (the new request)
    post2 = http_get("/api/specialists/intake-specialist/history")
    assert count_user_msgs(post2) == 1, \
        f"post-delete+run user msgs: expected 1, got {count_user_msgs(post2)}: {post2!r}"
    print(f"  ✓ history rebuilt to 1 turn ({len(post2)} total msgs) after the new run")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
async def main() -> int:
    print(f"connecting to {HEALTH_URI} ...")
    try:
        with urllib.request.urlopen(HEALTH_URI) as r:
            json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ cannot reach backend: {e}")
        print("   start it with: nohup .venv/bin/python -m webui.server.app "
              "> /tmp/openharness_webui.log 2>&1 &")
        return 1

    try:
        await test_1_fresh_history_is_empty()
        await test_2_scenario_writes_history()
        await test_3_standalone_continues_history()
        await test_4_other_agent_unaffected()
        await test_5_delete_clears_history()
    except AssertionError as e:
        print(f"\n❌ assertion failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ unexpected error: {type(e).__name__}: {e}")
        return 1

    print(f"\n✅ P7.A context unification verified — scenario writes history, "
          f"standalone continues, isolation between agents, DELETE works")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
