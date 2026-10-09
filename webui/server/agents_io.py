"""Read/write agent definitions from ~/.openharness/agents/*.md"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

# Make openharness importable from the project root
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from openharness.coordinator.agent_definitions import (  # noqa: E402
    get_all_agent_definitions,
    get_agent_definition,
)

from . import skills_io
from .models import Agent, AgentWrite

AGENTS_DIR = Path.home() / ".openharness" / "agents"

# Frontmatter fields that map directly from AgentWrite.
# Anything not listed here is dropped during serialization.
_FRONTMATTER_FIELDS = (
    "name",
    "subagent_type",
    "display_name",
    "description",
    "color",
    "skills",
    "tools",
    "model",
    "max_turns",
    "permission_mode",
    "background",
    "memory",
    "webui_qa_prompt",  # P7.B — optional WebUI Q&A mode prompt
)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into (frontmatter_dict, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    try:
        return yaml.safe_load(raw) or {}, body
    except yaml.YAMLError:
        return {}, body


def list_user_agent_files() -> list[Path]:
    """List user-defined agent .md files (skip built-ins)."""
    if not AGENTS_DIR.exists():
        return []
    return sorted(AGENTS_DIR.glob("*.md"))


def list_agents() -> list[Agent]:
    """Return only user-defined agents (those with a .md in AGENTS_DIR).

    The framework bundles 7 built-in subagent_types (general-purpose,
    statusline-setup, claude-code-guide, Explore, Plan, worker,
    verification). These are infrastructure for dispatching — they are NOT
    user-managed agents, so the webui management list excludes them.

    Built-ins that have been overridden by a user file (i.e. a same-named
    .md in AGENTS_DIR) still appear, because they ARE user-defined at
    that point.
    """
    out: list[Agent] = []
    user_files = {p.stem for p in list_user_agent_files()}

    # If a built-in has been overridden, the framework's loader exposes
    # the user version (user takes precedence over built-in). So we
    # can iterate the framework's view and simply skip names that have
    # no user file at all.
    for ad in get_all_agent_definitions():
        if ad.name not in user_files:
            continue
        out.append(Agent(
            name=ad.name,
            subagent_type=ad.subagent_type or ad.name,
            display_name=_read_user_display_name(ad.name),
            description=ad.description or "",
            color=ad.color or "gray",
            skills=ad.skills or [],
            tools=ad.tools or [],
            model=ad.model or "inherit",
            max_turns=ad.max_turns or 30,
            permission_mode=ad.permission_mode or "default",
            background=bool(ad.background),
            memory=ad.memory or "user",
            system_prompt_body=_read_user_body(ad.name),
            webui_qa_prompt=_read_user_qa_prompt(ad.name),  # P7.B
            role="coordinator" if "Agent" in (ad.tools or []) else "specialist",
        ))
    # Coordinators first, then specialists; stable within each group.
    out.sort(key=lambda a: (0 if a.role == "coordinator" else 1, a.name))
    return out


def _read_user_body(name: str) -> str:
    """Read the body (markdown after frontmatter) of a user agent file."""
    p = AGENTS_DIR / f"{name}.md"
    if not p.exists():
        return ""
    _, body = _split_frontmatter(p.read_text(encoding="utf-8"))
    return body


def _read_user_display_name(name: str) -> str:
    """Read the display_name field from a user agent's frontmatter.

    The framework's AgentDefinition model doesn't know about display_name,
    so we extract it from the raw file. Returns "" if missing.
    """
    p = AGENTS_DIR / f"{name}.md"
    if not p.exists():
        return ""
    fm, _ = _split_frontmatter(p.read_text(encoding="utf-8"))
    val = fm.get("display_name")
    return val if isinstance(val, str) else ""


def _read_user_qa_prompt(name: str) -> str:
    """P7.B — read the webui_qa_prompt field from a user agent's frontmatter.

    Like display_name, the framework doesn't know about this field, so we
    extract it from the raw file. Returns "" if missing.
    """
    p = AGENTS_DIR / f"{name}.md"
    if not p.exists():
        return ""
    fm, _ = _split_frontmatter(p.read_text(encoding="utf-8"))
    val = fm.get("webui_qa_prompt")
    return val if isinstance(val, str) else ""


def get_agent(name: str) -> Agent | None:
    """Get a single agent, including its body if it's a user agent."""
    ad = get_agent_definition(name)
    if ad is None:
        return None
    return Agent(
        name=ad.name,
        subagent_type=ad.subagent_type or ad.name,
        display_name=_read_user_display_name(ad.name),
        description=ad.description or "",
        color=ad.color or "gray",
        skills=ad.skills or [],
        tools=ad.tools or [],
        model=ad.model or "inherit",
        max_turns=ad.max_turns or 30,
        permission_mode=ad.permission_mode or "default",
        background=bool(ad.background),
        memory=ad.memory or "user",
        system_prompt_body=_read_user_body(name),
        webui_qa_prompt=_read_user_qa_prompt(name),  # P7.B
        role="coordinator" if "Agent" in (ad.tools or []) else "specialist",
    )


# ---------------------------------------------------------------------------
# Write / delete
# ---------------------------------------------------------------------------

# Names that are bundled with the framework and MUST NOT be deleted by the UI.
# They can still be overridden by writing a user file with the same name.
_BUILTIN_PROTECTED = {
    "general-purpose",
    "statusline-setup",
    "claude-code-guide",
    "Explore",
    "Plan",
    "worker",
    "verification",
}


def _agent_path(name: str) -> Path:
    return AGENTS_DIR / f"{name}.md"


def _validate_skill_refs(skill_names: list[str]) -> None:
    """Raise ValueError listing any skill names not present in the registry.

    Empty list is allowed (an agent may have no skills attached).
    """
    if not skill_names:
        return
    known = {s.name for s in skills_io.list_skills()}
    unknown = [n for n in skill_names if n not in known]
    if unknown:
        raise ValueError(f"unknown skill(s): {', '.join(unknown)}")


def _serialize(payload: AgentWrite) -> str:
    """Build the full markdown text (frontmatter + body) for an agent file."""
    data: dict[str, Any] = {k: getattr(payload, k) for k in _FRONTMATTER_FIELDS}
    # Normalize subagent_type default
    if not data.get("subagent_type"):
        data["subagent_type"] = data["name"]
    # Drop empty optionals to keep the file tidy
    for k in ("display_name", "description", "model", "memory"):
        if data.get(k) in ("", "inherit", "user") and k != "memory":
            if k == "model" and data[k] == "inherit":
                continue  # keep "inherit" — it's the framework default
            if k in ("display_name", "description") and data[k] == "":
                del data[k]
    # P7.B — drop empty webui_qa_prompt so .md files don't have a noisy
    # empty field. PyYAML dumps multi-line strings as `| literal block`,
    # which is fine for frontmatter.
    if data.get("webui_qa_prompt") == "":
        del data["webui_qa_prompt"]
    fm = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    body = payload.system_prompt_body.rstrip() + "\n" if payload.system_prompt_body else ""
    return f"---\n{fm}---\n\n{body}"


def write_agent(payload: AgentWrite) -> Agent:
    """Create or overwrite a user agent file. Returns the resulting Agent.

    Raises:
        ValueError: if `payload.skills` references names not in the registry.
    """
    _validate_skill_refs(payload.skills)
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _agent_path(payload.name)
    content = _serialize(payload)
    # Atomic write: write to tmp file in the same dir, then rename.
    fd, tmp = tempfile.mkstemp(prefix=f".{payload.name}.", suffix=".md.tmp", dir=AGENTS_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    a = get_agent(payload.name)
    if a is None:
        # Just wrote the file but the framework can't see it — extremely unlikely.
        raise RuntimeError(f"wrote {path} but agent not found in registry")
    return a


def delete_agent(name: str) -> bool:
    """Delete a user agent file.

    Returns True if a file was deleted, False if it didn't exist.
    Raises PermissionError if `name` is a built-in that has no user override
    (i.e. deleting it would remove the agent from the system entirely).
    """
    path = _agent_path(name)
    if not path.exists():
        # If the name is a known built-in, refuse — otherwise the agent
        # would just disappear with no record.
        if name in _BUILTIN_PROTECTED:
            raise PermissionError(f"refusing to delete built-in agent: {name}")
        return False
    path.unlink()
    return True
