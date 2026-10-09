"""Pydantic models for the webui API.

Shared between FastAPI and frontend (TypeScript types in src/types.ts mirror these).
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


AgentColor = Literal[
    "red", "green", "blue", "yellow", "purple",
    "orange", "cyan", "magenta", "white", "gray",
]

PermissionMode = Literal[
    "default", "acceptEdits", "bypassPermissions", "plan", "dontAsk",
]


class Skill(BaseModel):
    name: str
    domain: str = "general"
    path: str
    description: str = ""
    has_scripts: bool = False
    source: str = "user"  # user | bundled | project | plugin


class Agent(BaseModel):
    name: str
    subagent_type: str
    display_name: str = ""   # Chinese-friendly label; UI uses this, falls back to name
    description: str = ""
    color: AgentColor = "gray"
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    model: str = "inherit"
    max_turns: int = 30
    permission_mode: PermissionMode = "default"
    background: bool = False
    memory: str = "user"
    system_prompt_body: str = ""
    # P7.B — optional WebUI Q&A mode prompt. When non-empty, the
    # scenario_runner appends it to the system prompt at LLM call time
    # so the agent knows it's in direct Q&A mode (not CLI team mailbox
    # mode). UI checkbox in AgentEditor toggles whether this is set.
    webui_qa_prompt: str = ""
    role: str = "specialist"  # "coordinator" | "specialist"


class Health(BaseModel):
    status: str = "ok"
    agents_dir: str
    skills_dir: str


class AgentWrite(BaseModel):
    """Payload for create/update — same fields as Agent but stricter validation."""

    name: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]{0,63}$",
        description="kebab-case identifier, 1-64 chars",
    )
    subagent_type: str = Field(default="", max_length=64)
    display_name: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=500)
    color: AgentColor = "gray"
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    model: str = "inherit"
    max_turns: int = Field(default=30, ge=1, le=1000)
    permission_mode: PermissionMode = "default"
    background: bool = False
    memory: str = "user"
    system_prompt_body: str = Field(default="", max_length=20000)
    # P7.B — see Agent.webui_qa_prompt. 8000 chars (~2KB tokens) is enough
    # for a multi-paragraph "you're in WebUI Q&A mode" hint; not meant
    # to be a full system prompt on its own.
    webui_qa_prompt: str = Field(default="", max_length=8000)


class DeleteResult(BaseModel):
    deleted: str
    success: bool = True


class ErrorResult(BaseModel):
    error: str
    success: bool = False
