// Lightweight API client. The Vite dev server proxies /api -> http://localhost:8000.

import type { Agent, AgentColor, Health, PermissionMode, Skill } from "../types";

const BASE = "/api";

export interface AgentWritePayload {
  name: string;
  subagent_type: string;
  display_name: string;
  description: string;
  color: AgentColor;
  skills: string[];
  tools: string[];
  model: string;
  max_turns: number;
  permission_mode: PermissionMode;
  background: boolean;
  memory: string;
  system_prompt_body: string;
  /** P7.B — see Agent.webui_qa_prompt. Empty string = no QA prompt. */
  webui_qa_prompt: string;
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

/** Convert an Agent (read shape) into a write payload. */
export function agentToWritePayload(a: Agent): AgentWritePayload {
  return {
    name: a.name,
    subagent_type: a.subagent_type,
    display_name: a.display_name ?? "",
    description: a.description,
    color: a.color,
    skills: [...a.skills],
    tools: [...a.tools],
    model: a.model,
    max_turns: a.max_turns,
    permission_mode: a.permission_mode,
    background: a.background,
    memory: a.memory,
    system_prompt_body: a.system_prompt_body,
    webui_qa_prompt: a.webui_qa_prompt ?? "",  // P7.B
  };
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, text || res.statusText);
  }
  return res.json() as Promise<T>;
}

async function send<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health:        ()                          => get<Health>("/health"),
  agents:        ()                          => get<Agent[]>("/agents"),
  agent:         (n: string)                 => get<Agent>(`/agents/${encodeURIComponent(n)}`),
  skills:        ()                          => get<Skill[]>("/skills"),
  createAgent:   (payload: AgentWritePayload) => send<Agent>("POST",   "/agents", payload),
  updateAgent:   (n: string, payload: AgentWritePayload) => send<Agent>("PUT", `/agents/${encodeURIComponent(n)}`, payload),
  deleteAgent:   (n: string)                 => send<{deleted: string; success: boolean}>("DELETE", `/agents/${encodeURIComponent(n)}`),
};

// ---------------------------------------------------------------------------
// Scenario streaming (P3.1)
// ---------------------------------------------------------------------------

/** Discriminated union of all event types the server can emit.
 *
 *  Three scenario modes:
 *    - P3.4 classic:    scenario.start → specialist.* (4×) → synthesis.*
 *    - P9 plan_first:   same as classic, but specialists emit plan_return /
 *                       step_status before their text.
 *    - P10 coordinator: scenario.start (mode="coordinator") → coordinator.*
 *                       with specialist.* events nested between the
 *                       coordinator's tool_call and tool_result.
 *  The frontend handles all three; coordinator.* events are treated as
 *  a separate "supervisor" stream that produces its own final report.
 */
export type ScenarioEvent =
  | { type: "scenario.start";  request: string; team: string; ts: number; specialist_count?: number; mode?: string; coordinator?: string }
  | { type: "specialist.start"; name: string; color: string; label?: string; ts: number }
  | { type: "specialist.token"; name: string; delta: string; ts: number }
  | { type: "specialist.tool_call";   name: string; tool_id: string; tool_name: string; tool_input: any; ts: number }
  | { type: "specialist.tool_result"; name: string; tool_id: string; tool_name: string; output: string; is_error: boolean; ts: number }
  | { type: "specialist.plan_return"; name: string; rev: number; todos: any[]; ts: number }
  | { type: "specialist.step_status"; name: string; step_id: string; status: string; result?: string; error?: string; ts: number }
  | { type: "specialist.done";  name: string; text: string;  ts: number }
  | { type: "specialist.error"; name: string; detail: string; ts: number }
  | { type: "synthesis.start"; ts: number }
  | { type: "synthesis.token";  delta: string; ts: number }
  | { type: "synthesis.done";   text: string;  ts: number }
  | { type: "synthesis.error";  detail: string; ts: number }
  // P10 — coordinator (supervisor) events.  Specialist.* events can be
  // emitted between coordinator.tool_call and coordinator.tool_result
  // (nested inside a coordinator's dispatch/proceed/revise tool call).
  | { type: "coordinator.start";     name: string; ts: number }
  | { type: "coordinator.token";     delta: string; ts: number }
  | { type: "coordinator.tool_call"; tool_id: string; tool_name: string; tool_input: any; ts: number }
  | { type: "coordinator.tool_result"; tool_id: string; tool_name: string; output: string; is_error: boolean; ts: number }
  | { type: "coordinator.done";      text: string; ts: number }
  | { type: "coordinator.error";     detail: string; ts: number }
  | { type: "scenario.done";   status: string; ts: number; final_report?: string }
  | { type: "scenario.error";  detail: string; ts: number }
  | { type: "error";           detail: string; ts?: number };

export interface ScenarioHandle {
  ws: WebSocket;
  cancel: () => void;
}

/** Open a WebSocket to /ws/scenario and start a streaming run.

    The first message sent is `{type: "start", request, mode}`. The server
    then streams `ScenarioEvent` JSON frames until it emits `scenario.done`
    (or `scenario.error`), at which point it closes the socket.

    `mode` is P9/P10 opt-in:
      * "classic"     — default. P3.4 fan-out + synthesis (existing behavior).
      * "plan_first"  — P9. Each specialist MUST call plan() before executing.
      * "coordinator" — P10. Hierarchical supervisor: a coordinator LLM
                       drives the specialists via 7 internal tools
                       (dispatch / observe / proceed / revise /
                       finish_agent / assert_goal_coverage /
                       publish_final_report). Final report comes from
                       `coordinator.done`, not `synthesis.done`.

    P5 cancel protocol:
      * `cancel()` sends `{type:"cancel"}` JSON BEFORE closing the socket,
        so the server can cooperatively abort in-flight LLM tasks and emit
        a `scenario.done status="cancelled"` before closing.
      * `ws.onclose` is registered: if the socket closes before any
        terminal event was received (network drop, server crash), a
        synthetic `scenario.error` is emitted so the UI doesn't get stuck
        in "running". The `cancelledByClient` flag suppresses this when
        the disconnect was user-initiated.
*/
export function connectScenario(
  request: string,
  onEvent: (e: ScenarioEvent) => void,
  mode: "classic" | "plan_first" | "coordinator" = "classic",
): ScenarioHandle {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws/scenario`;
  const ws = new WebSocket(url);

  let cancelledByClient = false;
  let terminalReceived = false;

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "start", request, mode }));
  };
  ws.onmessage = (ev) => {
    let e: ScenarioEvent;
    try {
      e = JSON.parse(ev.data) as ScenarioEvent;
    } catch {
      return;
    }
    // Track whether a terminal event has been seen. If the WS closes
    // before this flag is set, onclose will surface a synthetic error.
    if (e.type === "scenario.done" || e.type === "scenario.error") {
      terminalReceived = true;
    }
    onEvent(e);
  };
  // P5: connection-level errors. Real-world failures (network drop, server
  // crash) usually fire `onclose` rather than `onerror` on the browser
  // side, but we keep this for the rare `onerror` case.
  ws.onerror = () => {
    if (cancelledByClient || terminalReceived) return;
    onEvent({
      type: "scenario.error",
      detail: "WebSocket error (see devtools)",
      ts: Date.now(),
    });
  };
  // P5: catch-all for any unexpected close. If the server has not yet
  // emitted a terminal event, surface a synthetic error so the UI can
  // transition out of "running" instead of hanging forever.
  ws.onclose = (ev) => {
    if (cancelledByClient) return;        // user-initiated, App already handled
    if (terminalReceived) return;          // clean close after a terminal event
    onEvent({
      type: "scenario.error",
      detail: `连接中断 (code=${ev.code}${ev.reason ? `, reason=${ev.reason}` : ""})`,
      ts: Date.now(),
    });
  };

  return {
    ws,
    cancel: () => {
      cancelledByClient = true;
      // Send the cancel message FIRST so the server can emit its own
      // terminal event before we close. If the socket is already gone
      // (e.g., the server crashed), the send throws and we just close.
      try { ws.send(JSON.stringify({ type: "cancel" })); } catch { /* already closed */ }
      try { ws.close(1000, "client cancel"); } catch { /* already closed */ }
    },
  };
}


// ---------------------------------------------------------------------------
// P6: per-specialist standalone testing
// ---------------------------------------------------------------------------

/** One step in the agent's "思考过程" region (tool call + result). */
export interface ProcessStep {
  id: string;             // tool_call_id
  tool_name: string;
  tool_input: any;
  output?: string;
  is_error?: boolean;
  status: "running" | "done" | "error";
  ts: number;
}

/** Discriminated union of all event types /ws/specialist can emit. */
export type SpecialistEvent =
  | { type: "specialist.start";     name: string; ts: number }
  | { type: "specialist.token";     delta: string; ts: number }
  | { type: "specialist.tool_call"; tool_id: string; tool_name: string; tool_input: any; ts: number }
  | { type: "specialist.tool_result"; tool_id: string; tool_name: string; output: string; is_error: boolean; ts: number }
  | { type: "specialist.done";      text: string; process: ProcessStep[]; ts: number }
  | { type: "specialist.error";     detail: string; ts: number }
  | { type: "cleared";              agentName: string; ts: number }
  | { type: "error";                detail: string; ts?: number };

export interface SpecialistHandle {
  ws: WebSocket;
  cancel: () => void;
  /** Ask the server to clear the agent's history list. */
  clear: () => void;
}

/** Open a WebSocket to /ws/specialist and start a single-specialist run.

    The first message sent is `{type: "start", agentName, request}`. The
    server reuses the per-agent history on the server side, so subsequent
    calls with the same `agentName` continue the conversation.

    P6 cancel protocol mirrors /ws/scenario: `cancel()` sends
    `{type:"cancel"}` BEFORE closing so the server can emit
    `specialist.error detail="cancelled"` cleanly.
*/
export function connectSpecialist(
  agentName: string,
  request: string,
  onEvent: (e: SpecialistEvent) => void,
): SpecialistHandle {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws/specialist`;
  const ws = new WebSocket(url);

  let cancelledByClient = false;
  let terminalReceived = false;

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "start", agentName, request }));
  };
  ws.onmessage = (ev) => {
    let e: SpecialistEvent;
    try {
      e = JSON.parse(ev.data) as SpecialistEvent;
    } catch {
      return;
    }
    if (e.type === "specialist.done" || e.type === "specialist.error" || e.type === "error") {
      terminalReceived = true;
    }
    onEvent(e);
  };
  ws.onerror = () => {
    if (cancelledByClient || terminalReceived) return;
    onEvent({
      type: "specialist.error",
      detail: "WebSocket error (see devtools)",
      ts: Date.now(),
    });
  };
  ws.onclose = (ev) => {
    if (cancelledByClient) return;
    if (terminalReceived) return;
    onEvent({
      type: "specialist.error",
      detail: `连接中断 (code=${ev.code}${ev.reason ? `, reason=${ev.reason}` : ""})`,
      ts: Date.now(),
    });
  };

  return {
    ws,
    cancel: () => {
      cancelledByClient = true;
      try { ws.send(JSON.stringify({ type: "cancel" })); } catch { /* already closed */ }
      try { ws.close(1000, "client cancel"); } catch { /* already closed */ }
    },
    clear: () => {
      try { ws.send(JSON.stringify({ type: "clear", agentName })); } catch { /* already closed */ }
    },
  };
}


// ---------------------------------------------------------------------------
// P7.A: per-specialist conversation history (REST)
// ---------------------------------------------------------------------------
// The server keeps one OpenAI-style message list per agent in
// `_specialist_history`, mutated in place by BOTH /ws/scenario and
// /ws/specialist. The frontend treats the SAME list as the source of
// truth for the timeline view, so a multi-domain run and a single-
// specialist follow-up see the same conversation.
//
// On mount the frontend calls getSpecialistHistory for each known
// specialist. Subsequent WS events (specialist.token / tool_call / done /
// error) are merged into the matching Turn via the helpers in App.tsx.

/** View model: one user + assistant (+ optional tool calls) exchange.
 *
 *  Source describes how this turn was started:
 *    - "standalone"  → /ws/specialist request
 *    - "scenario"    → /ws/scenario (the user_request went to 4 specialists
 *                      in parallel; this turn is what ONE of them produced)
 */
export interface Turn {
  /** Stable id for React keys. We use `<ts>_<source>` — collisions are
   *  extremely unlikely (two events for the same agent started in the
   *  same millisecond, same source) and harmless (key duplicates just
   *  trigger a console warning, not a crash). */
  id: string;
  agent_name: string;
  source: "standalone" | "scenario";
  /** The user's input that triggered this turn. */
  request: string;
  /** Accumulated assistant text (delta-concatenated from token events). */
  text: string;
  /** Tool calls and their results, in invocation order. */
  process: ProcessStep[];
  status: "running" | "done" | "error";
  errorDetail?: string;
  /** Start time (ms epoch, from server `ts` field, possibly in seconds). */
  ts: number;
  /** Set on done / error (ms epoch). */
  finishedTs?: number;
}

/** Convert seconds (server `ts`) to milliseconds (browser Date.now()).
 *  We accept both because earlier events used seconds; mount-loaded
 *  histories may mix the two. Anything > year 2100 in seconds is treated
 *  as already-millis. */
export function tsToMs(ts: number): number {
  return ts > 1e12 ? ts : ts * 1000;
}

/** Build a Turn from a fresh assistant message that just streamed in. */
export function newRunningTurn(
  agent_name: string,
  source: Turn["source"],
  request: string,
  ts: number,
): Turn {
  return {
    id: `${ts}_${source}`,
    agent_name,
    source,
    request,
    text: "",
    process: [],
    status: "running",
    ts: tsToMs(ts),
  };
}

/** Fetch a single agent's history. Returns [] when the agent has never
 *  been used (or is unknown to the server). */
export async function getSpecialistHistory(name: string): Promise<Turn[]> {
  // The server returns raw OpenAI message dicts. We translate them to
  // the frontend Turn view here so the rest of the app never sees the
  // raw shape.
  const raw = await get<Array<{ role: string; content?: string; tool_calls?: any[]; tool_call_id?: string }>>(
    `/specialists/${encodeURIComponent(name)}/history`,
  );
  return messagesToTurns(name, raw);
}

/** Server-side wipe of an agent's history. Idempotent. */
export async function clearSpecialistHistory(name: string): Promise<void> {
  await send<{ cleared: string; history: [] }>(
    "DELETE",
    `/specialists/${encodeURIComponent(name)}/history`,
  );
}

/** Convert a list of OpenAI messages (from the server) into a single
 *  Turn. The server stores one user msg + one assistant msg (+ N tool
 *  msgs) per turn. Tool messages are folded into the assistant's process
 *  array for UI rendering. */
function messagesToTurns(agent_name: string, msgs: Array<{
  role: string; content?: string; tool_calls?: any[]; tool_call_id?: string;
}>): Turn[] {
  if (msgs.length === 0) return [];

  // Walk through, group by user/assistant pairs. We treat the *first*
  // user message as the request and the subsequent assistant (+ tool)
  // messages as the response.
  const turns: Turn[] = [];
  let i = 0;
  while (i < msgs.length) {
    const m = msgs[i];
    if (m.role !== "user") {
      i += 1;
      continue;
    }
    const request = m.content ?? "";
    i += 1;
    // Collect subsequent assistant + tool messages as one turn
    let text = "";
    let process: ProcessStep[] = [];
    let status: Turn["status"] = "done";
    let errorDetail: string | undefined;
    let ts = Date.now();
    let finishedTs: number | undefined;
    while (i < msgs.length && msgs[i].role !== "user") {
      const x = msgs[i];
      if (x.role === "assistant") {
        text = x.content ?? "";
        // Map tool_calls back into the process array (id + name + raw args)
        if (Array.isArray(x.tool_calls)) {
          for (const tc of x.tool_calls) {
            let input: any = tc.function?.arguments;
            try {
              input = typeof input === "string" ? JSON.parse(input) : input;
            } catch { /* keep as string */ }
            process.push({
              id: tc.id,
              tool_name: tc.function?.name ?? "?",
              tool_input: input,
              status: "running",
              ts: Date.now(),
            });
          }
        }
      } else if (x.role === "tool") {
        const step = process.find((s) => s.id === x.tool_call_id);
        if (step) {
          step.output = x.content ?? "";
          step.status = "done";
        } else {
          // Orphan tool message — surface it as a step with a synthesized id
          process.push({
            id: x.tool_call_id ?? `orphan_${i}`,
            tool_name: "?",
            tool_input: {},
            output: x.content ?? "",
            status: "done",
            ts: Date.now(),
          });
        }
      }
      i += 1;
    }
    const turn: Turn = {
      id: `${ts}_history`,
      agent_name,
      source: "scenario",   // mount-loaded history defaults to scenario
      request,
      text,
      process,
      status,
      errorDetail,
      ts,
      finishedTs,
    };
    turns.push(turn);
  }
  return turns;
}
