"""Smoke test for P3.4 — verify the 5th (coordinator synthesis) LLM call.

Connects to ws://localhost:8000/ws/scenario and listens for events.
Asserts the new flow is present:
  - 4 specialist.start / .done events
  - 1 synthesis.start
  - many synthesis.token events (streaming)
  - 1 synthesis.done with a non-empty text
  - 1 scenario.done

Also prints the final synthesis text so we can eyeball the unified report.
"""
import asyncio
import json
import sys
from collections import Counter

import websockets


REQUEST = (
    "我家孩子 5 岁发烧 38.5°C 怎么办？请综合教育、医疗、IOT、NAS 四方面的建议。"
)


async def main() -> int:
    uri = "ws://localhost:8000/ws/scenario"
    print(f"connecting to {uri} ...")
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "start", "request": REQUEST}))
        print(f"sent request: {REQUEST!r}\n")

        type_counts: Counter[str] = Counter()
        specialist_done: dict[str, str] = {}
        synthesis_chunks: list[str] = []
        final_synthesis = ""
        last_error: str | None = None

        while True:
            raw = await ws.recv()
            evt = json.loads(raw)
            t = evt.get("type", "<no-type>")
            type_counts[t] += 1

            if t == "specialist.done":
                specialist_done[evt["name"]] = evt.get("text", "")
                # print first 80 chars so we can see it landed
                preview = (evt.get("text") or "")[:80].replace("\n", " ")
                print(f"  ✓ specialist.done  {evt['name']:20s}  {len(evt.get('text',''))} chars  '{preview}...'")
            elif t == "specialist.token":
                pass  # too noisy, just count
            elif t == "synthesis.start":
                print("\n  ⮕ synthesis.start  (5th LLM call begins)")
            elif t == "synthesis.token":
                synthesis_chunks.append(evt.get("delta", ""))
            elif t == "synthesis.done":
                final_synthesis = evt.get("text", "")
                print(f"  ✓ synthesis.done   {len(final_synthesis)} chars streamed")
            elif t == "synthesis.error":
                last_error = evt.get("detail", "")
            elif t == "scenario.done":
                print(f"\n  ✓ scenario.done  status={evt.get('status')}")
                break
            elif t == "scenario.error":
                last_error = evt.get("detail", "")
                print(f"\n  ✗ scenario.error  {last_error}")
                break

        # ---- summary ---------------------------------------------------------
        print("\n" + "=" * 72)
        print("EVENT SUMMARY")
        print("=" * 72)
        for k, v in sorted(type_counts.items()):
            print(f"  {k:25s} {v:>5}")
        print(f"  {'(streamed delta count)':25s} {len(synthesis_chunks):>5}")

        print("\n" + "=" * 72)
        print("SYNTHESIS TEXT (first 1200 chars)")
        print("=" * 72)
        print(final_synthesis[:1200])
        if len(final_synthesis) > 1200:
            print(f"\n... [+{len(final_synthesis) - 1200} more chars]")

        # ---- assertions -----------------------------------------------------
        ok = True
        problems = []

        if type_counts["specialist.start"] < 1:
            problems.append("no specialist.start events")
        if type_counts["specialist.done"] < 1:
            problems.append("no specialist.done events")
        if type_counts["synthesis.start"] != 1:
            problems.append(f"synthesis.start should be 1, got {type_counts['synthesis.start']}")
        if type_counts["synthesis.token"] < 5:
            problems.append(f"synthesis.token count too low ({type_counts['synthesis.token']}) — synthesis not streaming?")
        if not final_synthesis.strip():
            problems.append("synthesis text is empty")
        if "scenario.done" not in type_counts:
            problems.append("no scenario.done (terminal) event")

        # The synthesis must use a display_name as a section header (## ...).
        # At least one of: 医疗智能体, 教育智能体, IOT智能体, NAS智能体
        chinese_agents = ["医疗智能体", "教育智能体", "IOT智能体", "NAS智能体"]
        used_headers = [a for a in chinese_agents if f"## {a}" in final_synthesis]
        if not used_headers:
            problems.append("synthesis text does not contain a ## display_name header")
        else:
            print(f"\n  ✓ used display_name section headers: {used_headers}")

        # Check the medical disclaimer is present (required by the prompt).
        if "医疗免责" not in final_synthesis and "免责声明" not in final_synthesis:
            problems.append("medical disclaimer not found in synthesis")
        else:
            print("  ✓ medical disclaimer present")

        if problems:
            ok = False
            print("\n❌ PROBLEMS:")
            for p in problems:
                print(f"  - {p}")
        else:
            print("\n✅ all assertions passed")

        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
