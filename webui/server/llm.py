"""Real LLM client (OpenAI-compatible) for the webui scenario runner."""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

# Defaults: user's OpenRouter-local proxy
DEFAULT_BASE_URL = "http://192.168.60.202:5906/v1"
DEFAULT_MODEL = "Qwen3.6-27B"
DEFAULT_API_KEY = "sk-no-key-required"   # local proxy doesn't check


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("OPENAI_API_KEY", DEFAULT_API_KEY),
        )
    return _client


async def stream_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """Yield raw text tokens from a streaming chat completion.

    Args:
        messages: OpenAI-style [{role, content}, ...]
        model: override model name (default from env or Qwen3.6-27B)
        temperature: 0.0 - 2.0
        max_tokens: cap output length (None = unlimited)

    Yields:
        str tokens. Order is preserved; each is a delta from the previous.
    """
    client = get_client()
    kwargs: dict = {
        "model": model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


async def stream_chat_with_tools(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict]:
    """Yield typed events from a streaming chat completion with tool support.

    P6 — agent loop helper. Pattern copied from
    ``src/openharness/api/openai_client.py:332-414``: accumulate tool_call
    deltas across streaming chunks, then emit one ``tool_call`` event per
    tool at the end of the stream.

    Args:
        messages: OpenAI-style [{role, content, tool_calls?, tool_call_id?}, ...]
        model: override model name
        temperature: 0.0 - 2.0
        max_tokens: cap output length (None = unlimited)
        tools: OpenAI-format tool schemas:
            [{"type": "function", "function": {"name", "description", "parameters"}}]

    Yields:
        {"kind": "text",      "delta": str}
        {"kind": "tool_call", "id": str, "name": str, "input": dict}
        {"kind": "usage",     "input_tokens": int, "output_tokens": int}
        {"kind": "finish",    "reason": "stop" | "tool_calls" | "length" | ...}
    """
    client = get_client()
    kwargs: dict = {
        "model": model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if tools:
        kwargs["tools"] = tools

    collected_tool_calls: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None
    usage_data: dict[str, int] = {}

    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        if not chunk.choices:
            # Usage-only chunk
            if chunk.usage:
                usage_data = {
                    "input_tokens": chunk.usage.prompt_tokens or 0,
                    "output_tokens": chunk.usage.completion_tokens or 0,
                }
                yield {"kind": "usage", **usage_data}
            continue

        delta = chunk.choices[0].delta
        chunk_finish = chunk.choices[0].finish_reason

        if chunk_finish:
            finish_reason = chunk_finish

        # Stream text
        if delta and delta.content:
            yield {"kind": "text", "delta": delta.content}

        # Accumulate tool calls (id may come on first chunk, name+arguments on later)
        if delta and delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in collected_tool_calls:
                    collected_tool_calls[idx] = {
                        "id": tc_delta.id or "",
                        "name": "",
                        "arguments": "",
                    }
                entry = collected_tool_calls[idx]
                if tc_delta.id:
                    entry["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        entry["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        entry["arguments"] += tc_delta.function.arguments

        # Usage in chunk
        if chunk.usage:
            usage_data = {
                "input_tokens": chunk.usage.prompt_tokens or 0,
                "output_tokens": chunk.usage.completion_tokens or 0,
            }
            yield {"kind": "usage", **usage_data}

    # Emit one tool_call event per collected tool call (skips phantom/empty)
    for _idx in sorted(collected_tool_calls.keys()):
        tc = collected_tool_calls[_idx]
        if not tc["name"]:
            continue
        try:
            args = json.loads(tc["arguments"])
        except (json.JSONDecodeError, TypeError):
            args = {}
        yield {
            "kind": "tool_call",
            "id": tc["id"],
            "name": tc["name"],
            "input": args,
        }

    yield {"kind": "finish", "reason": finish_reason or "stop"}


# ---------------------------------------------------------------------------
# Non-streaming helper for short structured outputs (S5 入口分类 / 问诊规划)
# ---------------------------------------------------------------------------
async def chat_complete(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1500,
) -> str:
    """Single-shot chat completion. Returns the full text response.

    Use for short structured outputs (intent classification, intake planning).
    Do NOT use for long-form generation — use `stream_chat` instead.
    """
    client = get_client()
    resp = await client.chat.completions.create(
        model=model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )
    if not resp.choices:
        return ""
    return resp.choices[0].message.content or ""
