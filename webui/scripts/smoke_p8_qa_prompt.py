"""Smoke test for P7.B — verify the webui_qa_prompt frontmatter field.

What this test covers (5 tests):

  TEST 1 — POST /api/agents with webui_qa_prompt in the payload persists it
           and GET /api/agents/{name} reads it back.
  TEST 2 — PUT /api/agents/{name} can modify the field and the change is
           visible via GET.
  TEST 3 — When the field is empty ("") it is dropped from the .md file
           (clean YAML), and GET returns "".
  TEST 4 — When the field is set, the LLM's system prompt at call time
           includes the user's webui_qa_prompt. We monkey-patch
           `stream_chat_with_tools` to capture the messages list and
           assert that the system message contains a unique marker.
  TEST 5 — When the field is empty, the LLM's system prompt does NOT
           contain that marker.

Robustness:
  - We use a unique agent name `smoke-p8-agent` (kebab-case, valid).
    The test cleans it up at the start (DELETE if exists).
  - We monkey-patch via the module reference in scenario_runner, so the
    run_agent_turn function picks up the patched version transparently.
  - The .md file is written by the backend. After each test we read it
    back to verify serialization.

Run with backend running on :8000:
    python webui/scripts/smoke_p8_qa_prompt.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from typing import Any

SCENARIO_URI  = "ws://localhost:8000/ws/scenario"
HEALTH_URI    = "http://localhost:8000/api/health"
BASE          = "http://localhost:8000"
AGENT_NAME    = "smoke-p8-agent"
QA_MARKER     = "MUST_INCLUDE_QA_MARKER_12345"

AGENTS_DIR = os.path.expanduser("~/.openharness/agents")


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


def http_get(path: str) -> Any:
    with urllib.request.urlopen(f"{BASE}{path}") as r:
        return json.loads(r.read().decode("utf-8"))


def http_post(path: str, body: dict) -> Any:
    req = urllib.request.Request(
        f"{BASE}{path}", method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def http_put(path: str, body: dict) -> Any:
    req = urllib.request.Request(
        f"{BASE}{path}", method="PUT",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def http_delete(path: str) -> Any:
    req = urllib.request.Request(f"{BASE}{path}", method="DELETE")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def cleanup_agent() -> None:
    """Delete the smoke-p8-agent from both the API and the .md file."""
    try:
        http_delete(f"/api/agents/{AGENT_NAME}")
    except Exception:
        pass
    p = os.path.join(AGENTS_DIR, f"{AGENT_NAME}.md")
    if os.path.exists(p):
        os.unlink(p)


def read_md_file() -> str:
    p = os.path.join(AGENTS_DIR, f"{AGENT_NAME}.md")
    if not os.path.exists(p):
        return ""
    return open(p, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# TEST 1 — POST with webui_qa_prompt
# ---------------------------------------------------------------------------
def test_1_post_with_qa_prompt() -> None:
    banner("TEST 1: POST with webui_qa_prompt → GET reads it back")
    cleanup_agent()
    payload = {
        "name": AGENT_NAME,
        "subagent_type": AGENT_NAME,
        "display_name": "P8 测试 agent",
        "description": "smoke test for webui_qa_prompt field",
        "color": "blue",
        "skills": [],
        "tools": ["Bash", "Read"],
        "model": "inherit",
        "max_turns": 5,
        "permission_mode": "default",
        "background": False,
        "memory": "user",
        "system_prompt_body": "You are a test agent. Be terse.",
        "webui_qa_prompt": "TEST QA PROMPT 1",
    }
    created = http_post("/api/agents", payload)
    assert created.get("webui_qa_prompt") == "TEST QA PROMPT 1", \
        f"POST response missing webui_qa_prompt: {created!r}"
    print(f"  ✓ POST returned webui_qa_prompt = {created['webui_qa_prompt']!r}")

    got = http_get(f"/api/agents/{AGENT_NAME}")
    assert got.get("webui_qa_prompt") == "TEST QA PROMPT 1", \
        f"GET returned wrong webui_qa_prompt: {got.get('webui_qa_prompt')!r}"
    print(f"  ✓ GET reads it back = {got['webui_qa_prompt']!r}")

    # .md file should contain the field
    md = read_md_file()
    assert "webui_qa_prompt:" in md, \
        f".md file is missing webui_qa_prompt field:\n{md}"
    assert "TEST QA PROMPT 1" in md, \
        f".md file doesn't contain the QA text:\n{md}"
    print(f"  ✓ .md file contains webui_qa_prompt field with the text")


# ---------------------------------------------------------------------------
# TEST 2 — PUT modifies the field
# ---------------------------------------------------------------------------
def test_2_put_modifies() -> None:
    banner("TEST 2: PUT modifies webui_qa_prompt → persisted")
    got = http_get(f"/api/agents/{AGENT_NAME}")
    payload = {**got}  # copy all fields
    payload["webui_qa_prompt"] = "TEST QA PROMPT 2 (modified)"
    http_put(f"/api/agents/{AGENT_NAME}", payload)

    got2 = http_get(f"/api/agents/{AGENT_NAME}")
    assert got2.get("webui_qa_prompt") == "TEST QA PROMPT 2 (modified)", \
        f"PUT didn't persist: {got2.get('webui_qa_prompt')!r}"
    print(f"  ✓ PUT persisted: {got2['webui_qa_prompt']!r}")

    md = read_md_file()
    assert "TEST QA PROMPT 2 (modified)" in md, \
        f".md file doesn't reflect PUT:\n{md}"
    print(f"  ✓ .md file updated to new value")


# ---------------------------------------------------------------------------
# TEST 3 — Empty webui_qa_prompt is dropped from the .md file
# ---------------------------------------------------------------------------
def test_3_empty_dropped() -> None:
    banner("TEST 3: empty webui_qa_prompt → dropped from .md file")
    got = http_get(f"/api/agents/{AGENT_NAME}")
    payload = {**got}
    payload["webui_qa_prompt"] = ""  # clear
    http_put(f"/api/agents/{AGENT_NAME}", payload)

    md = read_md_file()
    assert "webui_qa_prompt:" not in md, \
        f"Empty field should be dropped, but .md still has it:\n{md}"
    print(f"  ✓ .md file no longer contains webui_qa_prompt: field")

    got2 = http_get(f"/api/agents/{AGENT_NAME}")
    assert got2.get("webui_qa_prompt") == "", \
        f"GET should return empty string, got {got2.get('webui_qa_prompt')!r}"
    print(f"  ✓ GET returns empty string")


# ---------------------------------------------------------------------------
# TEST 4 & 5 — LLM system prompt contains / doesn't contain the QA marker
# ---------------------------------------------------------------------------
# We capture the messages list by monkey-patching scenario_runner's
# stream_chat_with_tools IN THIS PROCESS, then drive run_agent_turn
# in-process (the same Python process the patch lives in).
#
# Why not /ws/specialist? The WebSocket runs in the *backend* process;
# monkey-patching this process's `scenario_runner` symbol doesn't reach
# the backend. smoke_p6_tool.py uses this same in-process pattern.

def _patch_stream_capture(scenario_runner, captured: list[dict]) -> Any:
    """Replace scenario_runner.stream_chat_with_tools with a deterministic
    stub that records `messages` then yields a single short text + finish.
    Returns the real original function (for later restore)."""
    real_stream = scenario_runner.stream_chat_with_tools

    async def patched(messages, *, model=None, temperature=0.7,
                      max_tokens=None, tools=None):
        # Snapshot messages at call time (runner mutates in place after)
        captured.append({"messages": [dict(m) for m in messages]})
        # Don't actually call the real LLM — return a deterministic
        # "ok" answer so run_agent_turn exits its loop on turn 1.
        yield {"kind": "text", "delta": "好的"}
        yield {"kind": "finish", "reason": "stop"}

    scenario_runner.stream_chat_with_tools = patched
    return real_stream


def _restore_stream(scenario_runner, real_stream) -> None:
    scenario_runner.stream_chat_with_tools = real_stream


async def _run_agent_turn_inprocess(scenario_runner, agent, request: str,
                                    captured: list[dict]) -> None:
    """Drive run_agent_turn inside this process so the patched
    stream_chat_with_tools fires. The agent passed in is the live
    Agent object loaded from disk (so its webui_qa_prompt reflects
    what the HTTP PUT just wrote)."""
    history: list[dict] = []
    async for ev in scenario_runner.run_agent_turn(
        agent, request, history=history,
    ):
        # Drain to agent_done
        if ev.get("kind") in ("agent_done", "agent_error"):
            break


async def test_4_marker_in_prompt_inprocess() -> None:
    banner("TEST 4: webui_qa_prompt SET → run_agent_turn system prompt contains marker")
    from webui.server import agents_io, scenario_runner

    # 1) PUT webui_qa_prompt = QA_MARKER (also have a non-empty body so the
    # fallback path doesn't fire)
    got = http_get(f"/api/agents/{AGENT_NAME}")
    payload = {**got}
    payload["webui_qa_prompt"] = QA_MARKER + " — please include this"
    http_put(f"/api/agents/{AGENT_NAME}", payload)

    # 2) Load the agent from disk (so webui_qa_prompt is current)
    agent = agents_io.get_agent(AGENT_NAME)
    assert agent is not None, f"agent {AGENT_NAME!r} should exist after PUT"

    # 3) Patch + run in-process
    captured: list[dict] = []
    real = _patch_stream_capture(scenario_runner, captured)
    try:
        await _run_agent_turn_inprocess(
            scenario_runner, agent, "回 OK 即可", captured,
        )
    finally:
        _restore_stream(scenario_runner, real)

    # 4) Assert the captured system prompt contains the marker
    assert len(captured) >= 1, \
        f"stream_chat_with_tools was never called for {AGENT_NAME}"
    msgs = captured[-1]["messages"]
    assert msgs and msgs[0].get("role") == "system", \
        f"first message should be system, got: {msgs[:1]!r}"
    system_content = msgs[0]["content"]
    assert QA_MARKER in system_content, \
        f"system prompt should contain QA_MARKER, got:\n{system_content}\n---"
    print(f"  ✓ LLM system prompt contains {QA_MARKER!r} "
          f"({len(system_content)} chars total)")


async def test_5_marker_absent_without_qa_inprocess() -> None:
    banner("TEST 5: webui_qa_prompt EMPTY → run_agent_turn system prompt does NOT contain marker")
    from webui.server import agents_io, scenario_runner

    # 1) Re-set to MARKER first (so we can prove clearing actually removes it)
    got = http_get(f"/api/agents/{AGENT_NAME}")
    payload = {**got}
    payload["webui_qa_prompt"] = QA_MARKER
    http_put(f"/api/agents/{AGENT_NAME}", payload)

    # 2) Then clear it
    payload["webui_qa_prompt"] = ""
    http_put(f"/api/agents/{AGENT_NAME}", payload)

    # 3) Load the agent from disk
    agent = agents_io.get_agent(AGENT_NAME)
    assert agent is not None, f"agent {AGENT_NAME!r} should exist after PUT"

    # 4) Patch + run in-process
    captured: list[dict] = []
    real = _patch_stream_capture(scenario_runner, captured)
    try:
        await _run_agent_turn_inprocess(
            scenario_runner, agent, "回 OK 即可", captured,
        )
    finally:
        _restore_stream(scenario_runner, real)

    # 5) Assert the captured system prompt does NOT contain the marker
    assert len(captured) >= 1, \
        f"stream_chat_with_tools was never called for {AGENT_NAME}"
    msgs = captured[-1]["messages"]
    assert msgs and msgs[0].get("role") == "system", \
        f"first message should be system, got: {msgs[:1]!r}"
    system_content = msgs[0]["content"]
    assert QA_MARKER not in system_content, \
        f"system prompt should NOT contain QA_MARKER when webui_qa_prompt is empty:\n{system_content}\n---"
    print(f"  ✓ LLM system prompt does NOT contain {QA_MARKER!r} "
          f"({len(system_content)} chars total)")


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
        return 1

    try:
        test_1_post_with_qa_prompt()
        test_2_put_modifies()
        test_3_empty_dropped()
        await test_4_marker_in_prompt_inprocess()
        await test_5_marker_absent_without_qa_inprocess()
    except AssertionError as e:
        print(f"\n❌ assertion failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ unexpected error: {type(e).__name__}: {e}")
        return 1
    finally:
        # Clean up the smoke agent
        cleanup_agent()

    print(f"\n✅ P7.B webui_qa_prompt verified — CRUD works, LLM prompt reflects it")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
