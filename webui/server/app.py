"""FastAPI app for the OpenHarness WebUI.

Phase 3.1 endpoints (P3.1):
  - GET    /api/health
  - GET    /api/agents
  - POST   /api/agents
  - GET    /api/agents/{name}
  - PUT    /api/agents/{name}
  - DELETE /api/agents/{name}
  - GET    /api/skills
  - POST   /api/intake/plan   (S2 — 问诊规划)
  - GET    /api/dashboard/stats  (S1 — 看板统计)
  - GET    /api/skills/{name}/agents
  - WS     /ws/scenario    (P3.1 — streams LLM tokens for a scenario)
  - WS     /ws/specialist  (P6 — single-specialist standalone testing + multi-turn)

P5 additions:
  - /ws/scenario now listens for `{type:"cancel"}` JSON messages and treats
    a client disconnect as an implicit cancel. Both paths feed the same
    `cancel: asyncio.Event` that `run_scenario` cooperates with, ensuring
    in-flight LLM tasks are cancelled and a `scenario.done
    status="cancelled"` is emitted before the WS closes.

P6 additions:
  - /ws/specialist — independent endpoint for testing one specialist in
    isolation, with server-side per-agent conversation history. Supports
    `cancel` and `clear` messages; emits `specialist.*` events.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import agents_io, scenario_runner, skills_io
from .dashboard_stats import collect_stats
from .knowledge_api import (
    list_books, list_chapters, list_entities,
    list_drug_interactions, list_cases, get_kg_relations,
)
from .suggestions import generate_suggestions
from .models import AgentWrite, DeleteResult, ErrorResult, Health

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("webui")

# Read port from environment variable, default to 9000
PORT = int(os.environ.get("OPENHARNESS_PORT", "9000"))

app = FastAPI(title="OpenHarness WebUI", version="0.1.0")

# OCR support - import with fallback
try:
    from openharness.config.settings import VisionModelConfig
    from openharness.tools.image_to_text_tool import ImageToTextTool, ImageToTextToolInput  # 添加 ImageToTextToolInput
    _ocr_imported = True
    print("[OCR] Dependencies imported successfully")
except ImportError as e:
    print(f"[OCR] Import failed: {e}")
    VisionModelConfig = None
    ImageToTextTool = None
    ImageToTextToolInput = None  # 添加这行
    _ocr_imported = False

# CORS for the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> Health:
    return Health(
        status="ok",
        agents_dir=str(agents_io.AGENTS_DIR),
        skills_dir=str(skills_io.SKILLS_DIR),
    )


@app.get("/api/agents")
def list_agents():
    return [a.model_dump() for a in agents_io.list_agents()]


@app.get("/api/agents/{name}")
def get_agent(name: str):
    a = agents_io.get_agent(name)
    if a is None:
        raise HTTPException(404, f"agent not found: {name}")
    return a.model_dump()


@app.post("/api/agents", status_code=201)
def create_agent(payload: AgentWrite):
    """Create a new user agent. Returns 409 if the name already exists."""
    # Allow overwriting a built-in (user file takes precedence) but
    # refuse to silently clobber an existing user file.
    if (agents_io.AGENTS_DIR / f"{payload.name}.md").exists():
        raise HTTPException(409, f"agent already exists: {payload.name}")
    try:
        a = agents_io.write_agent(payload)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        print(f"create_agent failed: {e}")
        raise HTTPException(500, f"create failed: {e}") from e
    return a.model_dump()


@app.put("/api/agents/{name}")
def update_agent(name: str, payload: AgentWrite):
    """Update an existing agent. The name in the URL is authoritative
    (payload.name must match, otherwise 400)."""
    if payload.name != name:
        raise HTTPException(400, f"payload.name={payload.name!r} != URL name={name!r}")
    # For built-ins with no user file, this *creates* the user override —
    # that's intentional, it's the only way to edit a built-in from the UI.
    try:
        a = agents_io.write_agent(payload)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        log.exception("update_agent failed")
        raise HTTPException(500, f"update failed: {e}") from e
    return a.model_dump()


@app.delete("/api/agents/{name}")
def delete_agent(name: str):
    """Delete a user agent file. Built-in names are protected."""
    try:
        deleted = agents_io.delete_agent(name)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    if not deleted:
        raise HTTPException(404, f"agent not found: {name}")
    return DeleteResult(deleted=name).model_dump()


@app.get("/api/skills")
def list_skills():
    return [s.model_dump() for s in skills_io.list_skills()]


@app.get("/api/skills/{name}/agents")
def list_agents_using_skill(name: str):
    """Return the list of agent names that include `name` in their skills list.

    Used by the future SkillSelector to show 'this skill is used by N agents'.
    Returns 404 if the skill itself does not exist.
    """
    skills = {s.name for s in skills_io.list_skills()}
    if name not in skills:
        raise HTTPException(404, f"skill not found: {name}")
    users = [a.name for a in agents_io.list_agents() if name in a.skills]
    return {"skill": name, "agents": users, "count": len(users)}


# ---------------------------------------------------------------------------
# 整改方案 §A7 — 看板统计接口
# 返回教材数 / 章节 / KG 实体 / KG 关系 / 药物互作对 / 病历 / 进化轮次等
# S1 阶段：基于 agent 描述 + 已知常量（source = "fallback"）
# S2-S4：逐步替换为真实查询（source = "live"）
# ---------------------------------------------------------------------------
@app.get("/api/dashboard/stats")
def dashboard_stats():
    """Aggregate stats for the home page 数据总览 section."""
    return collect_stats()


# ---------------------------------------------------------------------------
# 整改方案 S5-F.1 — 知识库 5 个 API
# ---------------------------------------------------------------------------
@app.get("/api/knowledge/books")
def knowledge_books(q: str | None = None):
    """列出医学教材，可按关键字过滤。"""
    return list_books(q)


@app.get("/api/knowledge/chapters")
def knowledge_chapters(book: str | None = None, limit: int = 20):
    """列出教材章节。book 不传时返回 5 本代表性教材的章节。"""
    return list_chapters(book, limit)


@app.get("/api/knowledge/entities")
def knowledge_entities(type: str | None = None, limit: int = 50):
    """列出 KG 实体（疾病/症状/药物/检查），可按类型过滤。"""
    return list_entities(type, limit)


@app.get("/api/knowledge/relations")
def knowledge_relations(limit: int = 30):
    """列出 KG 关系示例（疾病-症状-药物-检查）。"""
    return get_kg_relations(limit)


@app.get("/api/knowledge/drug-interactions")
def knowledge_drug_interactions(severity: str | None = None, limit: int = 50):
    """列出药物互作对，可按严重程度 (X/D/C/B) 过滤。"""
    return list_drug_interactions(severity, limit)


@app.get("/api/knowledge/cases")
def knowledge_cases(limit: int = 20):
    """列出病历。"""
    return list_cases(limit)


# ---------------------------------------------------------------------------
# 整改方案 S5-C — 智能建议 API
# ---------------------------------------------------------------------------
class SuggestionRequest(BaseModel):
    session_id: str | None = None
    refresh: bool = False


@app.post("/api/suggestions")
async def get_suggestions(req: SuggestionRequest):
    """根据 session 状态生成 3 条智能建议。LLM 驱动 + rule-based 兜底。"""
    result = await generate_suggestions(req.session_id, req.refresh)
    return result


# ---------------------------------------------------------------------------
# 整改方案 v2.1 §1 — 入口意图分类
# ---------------------------------------------------------------------------
# 用户输入 query 后，第一步先判断：
#   1. 是不是医疗？2. 是不是已有 session 的追问？3. 是否需要进问诊？
# 主路径：LLM（chat_complete）；LLM 失败时自动降级到 rule-based。
from .intake_classifier import classify_request, result_to_dict

class IntakeClassifyRequest(BaseModel):
    user_request: str = Field(default="", max_length=4000)
    session_id: str | None = None


@app.post("/api/intake/classify")
async def intake_classify(req: IntakeClassifyRequest):
    """入口意图分类（LLM 驱动）。返回 is_medical/needs_intent/intent/stages/reasoning。"""
    result = await classify_request(req.user_request, req.session_id)
    return result_to_dict(result)


# ---------------------------------------------------------------------------
# 整改方案 v2.1 §2 — 问诊规划（LLM 驱动）
# ---------------------------------------------------------------------------
from .intake_planner import generate_next_questions, plan_to_dict

class IntakePlanRequest(BaseModel):
    user_request: str = Field(default="", max_length=4000)
    partial_qa: dict[str, str] = Field(default_factory=dict)
    history: list[dict[str, str]] = Field(default_factory=list)
    max_questions: int = Field(default=5, ge=1, le=10)


@app.post("/api/intake/plan")
async def intake_plan(req: IntakePlanRequest):
    """根据 user_request + partial_qa + history，返回下一批问题。
    整改方案 v2.1 §2 — LLM 驱动，问题数量/内容/选项由 LLM 动态决定；
    LLM 不可用时降级到 rule-based 8 模板。
    """
    plan = await generate_next_questions(
        user_request=req.user_request,
        partial_qa=req.partial_qa or {},
        history=req.history or [],
        max_questions=req.max_questions,
    )
    return plan_to_dict(plan)


# ---------------------------------------------------------------------------
class IntakeCommitRequest(BaseModel):
    user_request: str
    qa: dict[str, str]
    session_id: str | None = None


@app.post("/api/intake/commit")
def intake_commit(req: IntakeCommitRequest):
    """前端答完所有题后调用一次，生成 patient_record 摘要并启动 session。

    S2 阶段：把 qa 整理成结构化 patient_record，存入 session.ctx，
    返回 { session_id, patient_record }，前端再带 session_id 调
    /ws/scenario mode=workflow。
    """
    import uuid as _uuid
    from .workflows import get_or_create_session
    sid = req.session_id or f"ses_{_uuid.uuid4().hex[:12]}"
    session = get_or_create_session(sid)

    # 构造 patient_record
    qa = req.qa
    patient = {
        "id": f"PT-{sid[-6:].upper()}",
        "name": qa.get("name", "未提供"),
        "age": qa.get("age", "未提供"),
        "gender": qa.get("gender", "未提供"),
        "chief_complaint": req.user_request,
        "duration": qa.get("main_symptom_duration", "未提供"),
        "associated": qa.get("associated_symptoms", "未提供"),
        "drug_allergy": qa.get("drug_allergy", "未提供"),
        "past_history": qa.get("past_history", "未提供"),
        "intake_qa": qa,
        "intake_completed": True,
    }
    session.ctx["user_request"] = req.user_request
    session.ctx["patient_record"] = patient
    session.ctx["intake_qa"] = qa

    return {
        "session_id": sid,
        "patient_record": patient,
    }


# ---------------------------------------------------------------------------
# P7.A: per-specialist conversation history (single source of truth)
# ---------------------------------------------------------------------------
# The same `_specialist_history` dict is mutated in place by both
# `/ws/scenario` (via the histories= kwarg to run_scenario) and
# `/ws/specialist` (via the per-specialist history parameter). The endpoints
# below let the frontend seed its timeline on mount (GET) and wipe a single
# agent's history (DELETE). The body is OpenAI message dicts directly —
# no Pydantic wrapper is needed because the frontend renders them as
# `Turn` view types keyed by `role`.
#
# We do NOT 404 on unknown agent names for these endpoints: the dict can
# be empty for a never-used agent, and we want the frontend to be able to
# fetch history for a specialist it just discovered without a prior GET
# /api/agents round-trip. The dict is created lazily on first write.
@app.get("/api/specialists/{name}/history")
def get_specialist_history(name: str):
    """Return the agent's conversation history as a list of OpenAI messages.

    Returns [] when the agent has never been used (or its name is unknown).
    """
    return _specialist_history.get(name, [])


@app.delete("/api/specialists/{name}/history")
def clear_specialist_history(name: str):
    """Clear the agent's history. Idempotent: returns the new (empty) list
    even if the agent was unknown."""
    if name in _specialist_history:
        _specialist_history[name] = []
    return {"cleared": name, "history": []}


# ---------------------------------------------------------------------------
# OCR API — 图片转文字（调用 vision 模型）
# ---------------------------------------------------------------------------
class OcrRequest(BaseModel):
    image_data: str = Field(..., description="Base64-encoded image data")
    media_type: str = Field(default="image/png", description="MIME type of the image")
    prompt: str = Field(
        default="你是一个图像识别助手。请详细描述图片内容，包括任何文字、物体、颜色、布局和上下文。如果图片包含医学相关内容（如化验单、病历、影像等），请特别关注并提取其中的关键信息。",
        description="Custom OCR instruction prompt",
    )


@app.post("/api/ocr")
async def ocr_image(req: OcrRequest):
    """使用 vision 模型将图片转换为文字描述。"""
    print("[OCR] Received request")
    
    # Check if OCR dependencies are available
    if not _ocr_imported:
        print("[OCR] Error: dependencies not imported")
        raise HTTPException(
            500,
            "OCR 功能不可用。请确保正确安装了 openharness 包及其依赖。",
        )

    vision_cfg = VisionModelConfig.from_env()
    print(f"[OCR] Model: {vision_cfg.model}, API Key set: {bool(vision_cfg.api_key)}")
    
    if not vision_cfg.model or not vision_cfg.api_key:
        print("[OCR] Error: model or api_key not configured")
        raise HTTPException(
            400,
            "vision 模型未配置。请设置 OPENHARNESS_VISION_MODEL 和 OPENHARNESS_VISION_API_KEY 环境变量。",
        )

    tool = ImageToTextTool()
    try:
        result = await tool.execute(
            ImageToTextToolInput(
                image_data=req.image_data,
                media_type=req.media_type,
                prompt=req.prompt,
                max_tokens=4096,
            ),
            type("ToolExecutionContext", (), {"metadata": {"vision_model_config": {
                "model": vision_cfg.model,
                "api_key": vision_cfg.api_key,
                "base_url": vision_cfg.base_url,
            }}, "cwd": Path(".")})(),
        )
        if result.is_error:
            raise HTTPException(400, result.output)
        return {"success": True, "text": result.output}
    except Exception as e:
        log.exception("OCR failed")
        raise HTTPException(500, f"OCR 处理失败: {str(e)}")


# ---------------------------------------------------------------------------
# WebSocket: scenario streaming (P3.1 + P5 cancel protocol)
# ---------------------------------------------------------------------------
@app.websocket("/ws/scenario")
async def scenario_ws(ws: WebSocket):
    """Client protocol:
        client → {type: "start",  request: "<text>"}      (initial)
        client → {type: "cancel"}                          (P5 — optional)
        server → {type: "scenario.start" | "specialist.start" |
                       "specialist.token" | "specialist.done" |
                       "scenario.done"  | "scenario.error", ...}

    P5 cancel: a `listen_for_cancel` task watches the socket in parallel
    with the scenario generator. If it sees a `{type:"cancel"}` message
    or detects a disconnect, it sets a shared `cancel: asyncio.Event` that
    `run_scenario` cooperates with. The generator aborts in-flight LLM
    tasks, drains its event queue, and emits a final `scenario.done
    status="cancelled"` before the WS closes.

    Connection closes after `scenario.done` or `scenario.error`.
    """
    await ws.accept()
    cancel = asyncio.Event()

    async def listen_for_cancel() -> None:
        """Set `cancel` when the client sends `{type:"cancel"}` or disconnects."""
        try:
            while True:
                m = await ws.receive_json()
                if isinstance(m, dict) and m.get("type") == "cancel":
                    log.info("scenario ws: client sent cancel")
                    cancel.set()
                    return
                # Other messages during a run are unexpected but harmless.
                # Ignore them and keep waiting for either cancel or disconnect.
        except WebSocketDisconnect:
            log.info("scenario ws: client disconnected (treated as cancel)")
            cancel.set()
        except Exception as e:
            log.info(f"scenario ws: cancel listener error ({type(e).__name__}); setting cancel")
            cancel.set()

    listener: asyncio.Task | None = None
    try:
        msg = await ws.receive_json()
        if not isinstance(msg, dict) or msg.get("type") != "start":
            await ws.send_json({"type": "error", "detail": "expected {type:'start', request:...}"})
            await ws.close()
            return
        user_request = (msg.get("request") or "").strip()
        if not user_request:
            await ws.send_json({"type": "error", "detail": "empty request"})
            await ws.close()
            return
        # P9 + P10 + S2: opt-in scenario modes. Default = "classic" so
        # existing callers and the frontend default UX are unchanged.
        #   "classic"      — P3.4 fan-out + 1-shot synthesis (P3.4 mode)
        #   "plan_first"   — P9 specialists must call plan() first
        #   "coordinator"  — P10 coordinator-driven hierarchical mode
        #   "workflow"     — S2 WorkflowScheduler (stage-based, intent-aware)
        # The frontend can pass {"type":"start", "request":"...", "mode":"plan_first"}
        # to require every specialist to call plan() before executing,
        # or mode="coordinator" to use the supervisor LLM.
        mode = (msg.get("mode") or "classic").strip()
        if mode not in ("classic", "plan_first", "coordinator", "workflow"):
            await ws.send_json({"type": "error", "detail": f"invalid mode: {mode!r}"})
            await ws.close()
            return
        # S2 — workflow 模式额外参数
        session_id = msg.get("session_id")
        stages_override = msg.get("stages")
        intent_override = msg.get("intent")
        log.info(f"scenario start: mode={mode} request={user_request[:60]!r}"
                 + (f" session={session_id}" if session_id else "")
                 + (f" stages={stages_override}" if stages_override else ""))

        # Start the cancel listener AFTER we've consumed the initial `start`.
        listener = asyncio.create_task(listen_for_cancel())

        # P7.A: share the module-level `_specialist_history` dict with the
        # runner so a multi-domain scenario ALSO writes each specialist's
        # in-place conversation history. After the run, switching to that
        # specialist's tab and sending a follow-up will see the scenario's
        # reply in its context (and vice versa).
        #
        # P10: in coordinator mode, route to the supervisor LLM loop
        # (run_coordinator_scenario) instead of the P3.4 fan-out.
        # Note: run_coordinator_scenario doesn't take a `mode` kwarg —
        # the mode is implied ("coordinator" since we picked this runner).
        # S2: in workflow mode, route to WorkflowScheduler-driven runner.
        if mode == "coordinator":
            runner = scenario_runner.run_coordinator_scenario
            runner_kwargs: dict = {
                "cancel": cancel,
                "histories": _specialist_history,
            }
        elif mode == "workflow":
            runner = scenario_runner.run_workflow_scenario
            runner_kwargs = {
                "cancel": cancel,
                "histories": _specialist_history,
                "session_id": session_id,
            }
            if stages_override:
                runner_kwargs["stages"] = stages_override
            if intent_override:
                runner_kwargs["intent"] = intent_override
            if msg.get("incremental"):
                runner_kwargs["incremental"] = True
        else:
            runner = scenario_runner.run_scenario
            runner_kwargs = {
                "cancel": cancel,
                "histories": _specialist_history,
                "mode": mode,
            }
        async for event in runner(user_request, **runner_kwargs):
            # If the cancel was set, drop intermediate events but keep
            # iterating so the generator can emit its terminal event
            # (`scenario.done status="cancelled"` or `scenario.done
            # status="synthesis_error"`) — the client still needs to see
            # a terminal to transition out of "running".
            if cancel.is_set() and event.get("type") not in ("scenario.done", "scenario.error"):
                continue
            try:
                await ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                cancel.set()
                break
    except WebSocketDisconnect:
        log.info("scenario ws: client disconnected")
        cancel.set()
    except Exception as e:
        log.exception("scenario ws error")
        cancel.set()
        try:
            await ws.send_json({"type": "error", "detail": str(e)})
        except Exception:
            pass
    finally:
        cancel.set()  # unblock the listener
        if listener is not None:
            listener.cancel()
            try:
                await listener
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# P6: WebSocket — per-specialist standalone testing + multi-turn history
# ---------------------------------------------------------------------------
# Module-level per-agent conversation history. Keyed by agent_name. The list
# is mutated in place by `scenario_runner.run_agent_turn`, so a second
# `{type:"start"}` against the same agent continues the conversation.
# Resets on process restart (matches user expectation).
_specialist_history: dict[str, list[dict]] = {}


@app.websocket("/ws/specialist")
async def specialist_ws(ws: WebSocket):
    """Per-specialist standalone testing with server-side history.

    Client protocol:
        client → {type: "start", agentName, request}      (initial)
        client → {type: "cancel"}                          (any time)
        client → {type: "clear", agentName}                (clear that agent's history)

    Server events (all carry `ts`):
        specialist.start
            name
        specialist.token       (many; `delta`)
        specialist.tool_call    (P6; `tool_id, tool_name, tool_input`)
        specialist.tool_result  (P6; `tool_id, tool_name, output, is_error`)
        specialist.done         (terminal; `text, process`)
        specialist.error        (terminal; `detail`)
        cleared                 (after a successful clear; `agentName`)

    The same `cancel` pattern as /ws/scenario is used: a listener task watches
    for cancel/clear/disconnect and sets a shared `asyncio.Event`; the agent
    loop checks `cancel.is_set()` between events and aborts.
    """
    await ws.accept()
    cancel = asyncio.Event()

    async def listen_for_cancel() -> None:
        """Set `cancel` on `{type:'cancel'}` or disconnect. Also handle `clear`."""
        try:
            while True:
                m = await ws.receive_json()
                if not isinstance(m, dict):
                    continue
                t = m.get("type")
                if t == "cancel":
                    log.info("specialist ws: client sent cancel")
                    cancel.set()
                    return
                if t == "clear":
                    target = m.get("agentName")
                    if isinstance(target, str) and target in _specialist_history:
                        _specialist_history[target] = []
                        try:
                            await ws.send_json({"type": "cleared", "agentName": target, "ts": time.time()})
                        except Exception:
                            pass
                    # Keep listening; the connection is still live.
        except WebSocketDisconnect:
            log.info("specialist ws: client disconnected (treated as cancel)")
            cancel.set()
        except Exception as e:
            log.info(f"specialist ws: listener error ({type(e).__name__}); setting cancel")
            cancel.set()

    listener: asyncio.Task | None = None
    try:
        first = await ws.receive_json()
        # P6: allow a standalone clear request (no prior start needed).
        # This is used by the client to wipe history after a `done` without
        # having to keep the previous connection alive.
        if isinstance(first, dict) and first.get("type") == "clear":
            target = first.get("agentName")
            if isinstance(target, str) and target in _specialist_history:
                _specialist_history[target] = []
            await ws.send_json({"type": "cleared", "agentName": target, "ts": time.time()})
            await ws.close()
            return
        if not isinstance(first, dict) or first.get("type") != "start":
            await ws.send_json({"type": "error", "detail": "expected {type:'start', agentName, request} or {type:'clear', agentName}"})
            await ws.close()
            return
        agent_name = first.get("agentName")
        request = (first.get("request") or "").strip()
        if not isinstance(agent_name, str) or not agent_name:
            await ws.send_json({"type": "error", "detail": "agentName required"})
            await ws.close()
            return
        if not request:
            await ws.send_json({"type": "error", "detail": "request required"})
            await ws.close()
            return

        agent = next((a for a in agents_io.list_agents() if a.name == agent_name), None)
        if agent is None:
            await ws.send_json({"type": "error", "detail": f"agent not found: {agent_name}"})
            await ws.close()
            return

        log.info(f"specialist start: agent={agent_name!r} request={request[:60]!r}")

        # Start listener (consumes cancel/clear messages while agent runs)
        listener = asyncio.create_task(listen_for_cancel())

        # Get-or-create the per-agent history. This is the same list the
        # next /ws/specialist call against the same agent will see, so
        # subsequent messages continue the conversation.
        history = _specialist_history.setdefault(agent_name, [])

        await ws.send_json({"type": "specialist.start", "name": agent_name, "ts": time.time()})

        chunks: list[str] = []
        process_steps: list[dict] = []
        failed: str | None = None
        try:
            async for ev in scenario_runner.run_agent_turn(
                agent,
                request,
                history=history,
                cancel=cancel,
            ):
                if cancel.is_set() and ev["kind"] not in ("agent_done", "agent_error"):
                    continue
                if ev["kind"] == "text":
                    chunks.append(ev["delta"])
                    await ws.send_json({
                        "type": "specialist.token",
                        "delta": ev["delta"],
                        "ts": time.time(),
                    })
                elif ev["kind"] == "tool_call":
                    await ws.send_json({
                        "type": "specialist.tool_call",
                        "tool_id": ev["id"],
                        "tool_name": ev["name"],
                        "tool_input": ev["input"],
                        "ts": time.time(),
                    })
                    process_steps.append({
                        "id": ev["id"],
                        "tool_name": ev["name"],
                        "tool_input": ev["input"],
                        "status": "running",
                        "ts": time.time(),
                    })
                elif ev["kind"] == "tool_result":
                    await ws.send_json({
                        "type": "specialist.tool_result",
                        "tool_id": ev["id"],
                        "tool_name": ev["name"],
                        "output": ev["output"],
                        "is_error": ev["is_error"],
                        "ts": time.time(),
                    })
                    # Update the corresponding running step in place
                    for s in process_steps:
                        if s.get("id") == ev["id"]:
                            s["output"] = ev["output"]
                            s["is_error"] = ev["is_error"]
                            s["status"] = "error" if ev["is_error"] else "done"
                            break
                elif ev["kind"] == "turn_done":
                    pass
                elif ev["kind"] == "agent_done":
                    break
                elif ev["kind"] == "agent_error":
                    failed = ev["detail"]
                    break
        except Exception as e:
            log.exception("specialist agent loop error")
            failed = f"{type(e).__name__}: {e}"

        if failed is not None:
            await ws.send_json({
                "type": "specialist.error",
                "detail": failed,
                "ts": time.time(),
            })
        else:
            await ws.send_json({
                "type": "specialist.done",
                "text": "".join(chunks),
                "process": process_steps,
                "ts": time.time(),
            })
    except WebSocketDisconnect:
        log.info("specialist ws: client disconnected")
        cancel.set()
    except Exception as e:
        log.exception("specialist ws error")
        cancel.set()
        try:
            await ws.send_json({"type": "error", "detail": str(e)})
        except Exception:
            pass
    finally:
        cancel.set()
        if listener is not None:
            listener.cancel()
            try:
                await listener
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Static files (built frontend) — only mounted in production
# ---------------------------------------------------------------------------
WEBUI_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = WEBUI_DIR / "dist"

# ---------------------------------------------------------------------------
# Speech to Text API (语音转文字)
# ---------------------------------------------------------------------------
class SpeechToTextRequest(BaseModel):
    audio_data: str = Field(..., description="Base64-encoded audio data")
    media_type: str = Field(default="audio/webm", description="MIME type of the audio")
    provider: str = Field(default="browser", description="识别模式: browser | baidu")


@app.post("/api/speech-to-text")
async def speech_to_text(req: SpeechToTextRequest):
    """语音转文字 API"""
    print(f"[Speech] Received request - Provider: {req.provider}")
    
    # 浏览器模式：前端已处理
    if req.provider == "browser":
        return {"success": True, "text": ""}
    
    try:
        import base64
        audio_bytes = base64.b64decode(req.audio_data)
        
        # if req.provider == "groq":
        #     api_key = os.environ.get("GROQ_API_KEY")
        #     if not api_key:
        #         raise HTTPException(400, "GROQ_API_KEY 环境变量未设置")
        #     
        #     from openharness.providers.transcription import GroqTranscriptionProvider
        #     transcriber = GroqTranscriptionProvider(api_key=api_key)
        #     
        #     import tempfile
        #     with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        #         f.write(audio_bytes)
        #         temp_path = Path(f.name)
        #     
        #     try:
        #         text = await transcriber.transcribe(temp_path)
        #     finally:
        #         temp_path.unlink()
        
        # elif req.provider == "openai":
        #     api_key = os.environ.get("OPENAI_API_KEY")
        #     if not api_key:
        #         raise HTTPException(400, "OPENAI_API_KEY 环境变量未设置")
        #     
        #     from openai import AsyncOpenAI
        #     client = AsyncOpenAI(api_key=api_key)
        #     
        #     import io
        #     audio_file = io.BytesIO(audio_bytes)
        #     audio_file.name = "audio.webm"
        #     
        #     response = await client.audio.transcriptions.create(
        #         model="whisper-1",
        #         file=audio_file,
        #         response_format="text",
        #         language="zh"
        #     )
        #     text = response.strip()
        
        if req.provider == "baidu":
            api_key = os.environ.get("BAIDU_API_KEY")
            secret_key = os.environ.get("BAIDU_SECRET_KEY")
            if not api_key:
                raise HTTPException(400, "BAIDU_API_KEY 环境变量未设置")
            if not secret_key:
                raise HTTPException(400, "BAIDU_SECRET_KEY 环境变量未设置")
            
            from openharness.providers.transcription import BaiduTranscriptionProvider
            transcriber = BaiduTranscriptionProvider(api_key=api_key, secret_key=secret_key)
            
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
                f.write(audio_bytes)
                temp_path = Path(f.name)
            
            try:
                text = await transcriber.transcribe(temp_path)
            finally:
                temp_path.unlink()
        
        else:
            raise HTTPException(400, f"未知的 provider: {req.provider}")
        
        if text:
            return {"success": True, "text": text}
        else:
            raise HTTPException(500, "未能识别语音内容")
    
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Speech to text failed")
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Static files (built frontend) — only mounted in production
# ---------------------------------------------------------------------------
WEBUI_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = WEBUI_DIR / "dist"

if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(DIST_DIR / "index.html")

    log.info(f"Serving built frontend from {DIST_DIR}")
else:
    log.info(f"No built frontend at {DIST_DIR} (run `npm run build` to enable static serving)")


if __name__ == "__main__":
    import uvicorn
    
    # Print all registered routes for debugging
    print(f"\n=== Registered Routes ===")
    for route in app.routes:
        methods = getattr(route, 'methods', 'N/A')
        path = getattr(route, 'path', 'N/A')
        print(f"  {methods} {path}")
    print(f"========================\n")
    
    print(f"Starting OpenHarness WebUI on port {PORT}")
    log.info(f"Starting OpenHarness WebUI on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")