// Main app — top-level layout.
//  - Top bar
//  - 3-column body: TaskPanel (left, S2) | ScenarioView (middle) | (no right panel, S1 A6)
//  - Modals: AgentEditor (create/edit), ConfirmDialog (delete), QuestionDialog (S2)
//
// S2 整改方案 §S2 接线：
//   - SystemPanel 替换为 TaskPanel（任务清单 + 串/并标识 + 展开历史）
//   - 新增 intake 状态机：用户输入 → QuestionDialog 问诊 → commit → workflow
//   - 新增 /ws/scenario mode="workflow" 路径
//   - 新事件 stage.start/done/error + agent.*(带 stage) 驱动 TaskPanel
//
// P4 / P6 / P7.A 历史注释保留，向后兼容旧的 classic / coordinator 模式。
//
// P6 — process visibility + per-specialist tab rewrite:
//   - onSelectAgent (Overview card click) now jumps to the specialist tab
//     (setActiveTab) instead of opening the right DetailPanel.
//   - Tool_call / tool_result events are surfaced in the specialist tab.
//
// P7.A — context unification:
//   - The per-agent conversation history on the server (`_specialist_history`)
//     is now the single source of truth for BOTH /ws/scenario and
//     /ws/specialist. The frontend mirrors it as `specialistHistories:
//     Record<name, Turn[]>` and reuses the same update path for both modes.
//   - On mount, the frontend GETs each specialist's history from
//     /api/specialists/{name}/history and seeds the timeline.
//   - The previous `specialistRun` standalone state and `effectiveRuntimes`
//     overlay are gone — the latest Turn in each agent's history is the
//     live runtime, and the full list is the timeline.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  agentToWritePayload, api, ApiError, clearSpecialistHistory as apiClearHistory,
  connectSpecialist, getSpecialistHistory,
  newRunningTurn, type ProcessStep, type ScenarioHandle,
  type SpecialistEvent, type SpecialistHandle, type Turn, tsToMs,
} from "./api/client";
import type { Agent, Skill } from "./types";
import { TopBar } from "./components/TopBar";
import { ScenarioView, type SpecialistRuntime, type TabId } from "./components/ScenarioView";
import type { TaskRow } from "./components/TaskRow";
import { AgentEditor } from "./components/AgentEditor";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { QuestionDialog } from "./components/QuestionDialog";
import { useIntake } from "./hooks/useIntake";

type Status = "idle" | "planning" | "running" | "synthesizing" | "done" | "error";
type SpecStatus = "idle" | "running" | "done" | "error";

type EditorState =
  | { kind: "closed" }
  | { kind: "create" }
  | { kind: "edit"; agent: Agent };

// ---------------------------------------------------------------------------
// P7.A: history state helpers (pure, immutable, predictable)
// ---------------------------------------------------------------------------
// All helpers take the current Record<name, Turn[]> and return a NEW record.
// This keeps React's referential-equality bailouts working: only the key
// that changed gets a new list reference.

/** Append a new running Turn for `name`. Used when the first specialist.start
 *  (or specialist.start from /ws/specialist) is received. */
function appendRunningTurn(
  h: Record<string, Turn[]>, turn: Turn,
): Record<string, Turn[]> {
  const cur = h[turn.agent_name] ?? [];
  return { ...h, [turn.agent_name]: [...cur, turn] };
}

/** Apply an updater to the last (running) Turn of `name`. If there's no
 *  running turn, the call is a no-op (rare race during cancellation). */
function updateLastRunning(
  h: Record<string, Turn[]>, name: string,
  updater: (t: Turn) => Turn,
): Record<string, Turn[]> {
  const turns = h[name];
  if (!turns || turns.length === 0) return h;
  const last = turns[turns.length - 1];
  if (last.status !== "running") return h;
  const updated = updater(last);
  return { ...h, [name]: [...turns.slice(0, -1), updated] };
}

function appendTokenDelta(
  h: Record<string, Turn[]>, name: string, delta: string,
): Record<string, Turn[]> {
  return updateLastRunning(h, name, (t) => ({ ...t, text: t.text + delta }));
}

function appendProcessStep(
  h: Record<string, Turn[]>, name: string, step: ProcessStep,
): Record<string, Turn[]> {
  return updateLastRunning(h, name, (t) => ({ ...t, process: [...t.process, step] }));
}

function markProcessStep(
  h: Record<string, Turn[]>, name: string, stepId: string,
  output: string, isError: boolean,
): Record<string, Turn[]> {
  return updateLastRunning(h, name, (t) => ({
    ...t,
    process: t.process.map((p) =>
      p.id === stepId
        ? { ...p, output, is_error: isError, status: isError ? "error" : "done" }
        : p,
    ),
  }));
}

function finalizeTurn(
  h: Record<string, Turn[]>, name: string,
  text: string, process: ProcessStep[], finishedTs: number,
): Record<string, Turn[]> {
  return updateLastRunning(h, name, (t) => ({
    ...t,
    text: text || t.text,
    process: process && process.length > 0 ? process : t.process,
    status: "done",
    finishedTs,
  }));
}

function errorTurn(
  h: Record<string, Turn[]>, name: string, detail: string, finishedTs: number,
): Record<string, Turn[]> {
  return updateLastRunning(h, name, (t) => ({
    ...t,
    status: "error",
    errorDetail: detail,
    finishedTs,
  }));
}

export function App() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [tokens, setTokens] = useState(0);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState>({ kind: "closed" });
  const [pendingDelete, setPendingDelete] = useState<Agent | null>(null);
  // P3: confirm dialog for clearing a specialist's history. Same pattern
  // as `pendingDelete`: null = no dialog, otherwise the agent whose history
  // is about to be wiped.
  const [pendingClearHistory, setPendingClearHistory] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [savingSkillsFor, setSavingSkillsFor] = useState<string | null>(null);
  // 整改方案 §A1 — 默认 Tab 改为"主页"。
  const [activeTab, setActiveTab] = useState<TabId>("home");

  // S2 — 问诊 dialog 控制
  const [intakeOpen, setIntakeOpen] = useState(false);
  const [intakeInitialRequest, setIntakeInitialRequest] = useState<string | null>(null);
  // S2 — 当前的 session_id（问诊 commit 后获得）
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // S2 — workflow 任务清单（驱动 TaskPanel）
  const [taskRows, setTaskRows] = useState<TaskRow[]>([]);
  const [intentMeta, setIntentMeta] = useState<{ round?: number; intent?: string; stages?: string[] }>({});

  // P3.3 — per-specialist runtime state. Derived from the latest Turn in
  // P7.A's `specialistHistories`, NOT maintained independently.
  const [specialists, setSpecialists] = useState<Record<string, SpecialistRuntime>>({});
  // P3.3 — synthesis (final report) text
  const [synthesisText, setSynthesisText] = useState("");
  // S4-B — 旧 classic/coordinator 模式回退开关已下线，所有请求统一走 workflow
  // （弹问诊 → WorkflowScheduler）。scenarioMode 状态本身移除。

  // P4 — DetailPanel 已并入"团队管理" Tab（TeamPane），不再作为右侧栏。
  // 保留 panelOpen 状态以兼容旧 props，但 UI 上不再渲染。
  const [panelOpen, setPanelOpen] = useState(false);
  // S5-F.2 — 知识库面板聚焦目标（specialist timeline 里点击引用时设）
  const [knowledgeFocus, setKnowledgeFocus] = useState<{ type: "books" | "chapters" | "cases"; id: string } | null>(null);
  // P4 — chronological event log for the SystemPanel.
  // S4-B — events 状态已下线（旧 SystemPanel 事件流删除后无消费者）。
  // P4 — when the current scenario started (for elapsed-time display).
  const [startedAt, setStartedAt] = useState<number | null>(null);

  // P5 — flag set by onCancelScenario so the event handler discards any
  // residual events the server flushes out (e.g., a few `specialist.token`
  // stragglers, or the trailing `scenario.done status="cancelled"`) before
  // the WS finally closes.
  const cancelledRef = useRef(false);

  // P7.A — per-agent conversation history, the single source of truth.
  // Keyed by agent name. Each list is the chronological timeline for that
  // agent. The latest turn in the list is the agent's current "live"
  // runtime (status + accumulated text + process). Both /ws/scenario and
  // /ws/specialist flows append to the same list.
  const [specialistHistories, setSpecialistHistories] = useState<Record<string, Turn[]>>({});

  // P6 — flag set by onCancelSpecialist. Mirrors the scenario pattern.
  const cancelledSpecRef = useRef(false);

  // 整改方案 §A6 — DetailPanel 已不再渲染，detailPanelRef /
  // useOutsideClick 整段移除。panelOpen state 保留以便将来可能复用。

  // WebSocket handle for the running scenario (null when idle)
  const scenarioRef = useRef<ScenarioHandle | null>(null);
  // P6 — WebSocket handle for the running standalone specialist run
  const specialistRef = useRef<SpecialistHandle | null>(null);
  // E2 — 标记 report stage 是否已经开始流式输出（用于只跳一次报告 tab）
  const reportStartedRef = useRef(false);

  const reload = useCallback(async () => {
    try {
      const [a, s] = await Promise.all([api.agents(), api.skills()]);
      setAgents(a);
      setSkills(s);
      // If the currently selected agent no longer exists, fall back
      if (selected && !a.find((x) => x.name === selected)) {
        setSelected(a[0]?.name ?? null);
      }
    } catch (e) {
      setError(String(e));
    }
  }, [selected]);

  // P7.A — load all specialist histories on mount so the timeline is
  // populated immediately, not just when the user clicks a tab.
  const loadAllHistories = useCallback(async (agentNames: string[]) => {
    const results: Array<[string, Turn[]]> = await Promise.all(
      agentNames.map(async (name): Promise<[string, Turn[]]> => {
        try {
          return [name, await getSpecialistHistory(name)];
        } catch {
          return [name, []];
        }
      }),
    );
    const out: Record<string, Turn[]> = {};
    for (const [name, turns] of results) out[name] = turns;
    setSpecialistHistories((cur) => ({ ...cur, ...out }));
  }, []);

  useEffect(() => {
    reload(); /* eslint-disable-line react-hooks/exhaustive-deps */
  }, []);

  // P7.A — fetch histories for all known specialists as soon as `agents`
  // is loaded. We re-run when the agent list changes (new specialist
  // created / deleted).
  useEffect(() => {
    if (agents.length === 0) return;
    loadAllHistories(agents.filter((a) => a.role !== "coordinator").map((a) => a.name));
  }, [agents, loadAllHistories]);

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  // Cleanup WS on unmount
  useEffect(() => {
    return () => {
      scenarioRef.current?.cancel();
      specialistRef.current?.cancel();
    };
  }, []);

  // S4-B — webui:scenario-mode 监听已移除（旧模式回退开关下线）。


  const selectedAgent = agents.find((a) => a.name === selected) ?? null;
  const userSpecialists = agents.filter((a) => a.role !== "coordinator");

  // P7.A — derive the latest-turn-per-agent view as the SpecialistRuntime
  // map used by the Overview cards. The latest turn's status / text /
  // process / errorDetail feed the card. If the agent has no history at
  // all, the runtime is "idle" with empty text.
  const specialistRuntimes: Record<string, SpecialistRuntime> = useMemo(() => {
    const out: Record<string, SpecialistRuntime> = {};
    for (const a of userSpecialists) {
      const turns = specialistHistories[a.name];
      const last = turns && turns.length > 0 ? turns[turns.length - 1] : null;
      if (last) {
        out[a.name] = {
          text: last.text,
          status: last.status === "running" ? "running"
                : last.status === "error"   ? "error"
                : "done",
          process: last.process,
          errorDetail: last.errorDetail,
        };
      } else {
        out[a.name] = { text: "", status: "idle", process: [] };
      }
    }
    return out;
  }, [userSpecialists, specialistHistories]);

  interface ImageAttachment {
    id: string;
    url: string;
    name: string;
    size: number;
    file: File;
    ocrText?: string;
    ocrStatus?: "idle" | "processing" | "done" | "error";
}

  function onSend(q: string, images?: ImageAttachment[]) {
    if (scenarioRef.current) return;   // guard: don't double-send

    let fullRequest = q;
    if (images && images.length > 0) {
      for (const img of images) {
        if (img.ocrText) {
          fullRequest += `\n\n[图片 ${img.name} 的 OCR 识别结果]\n${img.ocrText}`;
        }
      }
    }

    setIntakeInitialRequest(fullRequest);
    setIntakeOpen(true);
    void (async () => {
      const store = useIntake.getState();
      const cls = await store.classify(fullRequest, activeSessionId);
      if (!cls) return;  // classify 失败（网络错误等）→ 用户在弹窗里看错误
      if (!cls.is_medical) {
        // 非医疗：弹窗停留在 non_medical 状态
        return;
      }
      if (!cls.needs_intake) {
        // 追问场景：直接 startWorkflow，不进问诊
        // S5-E — 增量模式：让协调者只跑 report，做增量报告（保留上轮结论 + 回答本次追问）
        setIntakeOpen(false);
        if (cls.stages.length > 0) {
          // 用伪 patient_record 触发 workflow；incremental=true 让后端只跑 report stage
          // 并把 report prompt 切到「增量更新」模板
          startWorkflow(fullRequest, activeSessionId ?? `ses_followup_${Date.now()}`, true);
        }
        return;
      }
      // 进问诊：调 /api/intake/plan 拿 LLM 生成的第一批题
      try {
        const r = await fetch("/api/intake/plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_request: fullRequest, partial_qa: {} }),
        });
        if (!r.ok) return;
        const plan = await r.json();
        store.setPlan(plan);
      } catch (e) {
        console.error("intake plan failed:", e);
      }
    })();
  }

  function onCancelScenario() {
    if (!scenarioRef.current) return;
    cancelledRef.current = true;        // P5 — drop residual events
    scenarioRef.current.cancel();
    scenarioRef.current = null;
    setStatus("idle");
    setQuery(null);
    setActiveTab("home");               // 整改方案 §A1: 取消后回到主页
  }


  // S5-F.2 — specialist timeline 里的引用链接 → 跳知识库面板
  function onJumpToKnowledge(target: { type: "books" | "chapters" | "cases"; id: string }) {
    setKnowledgeFocus(target);
    setActiveTab("knowledge");
    setToast(`🎯 已聚焦知识库：${target.type} / ${target.id}`);
  }

  // S2 — 启动 workflow (从 QuestionDialog 回调进来)
  function startWorkflow(userRequest: string, sessionId: string, incremental: boolean = false) {
    if (scenarioRef.current) return;
    setQuery(userRequest);
    setActiveSessionId(sessionId);
    setSynthesisText("");
    setTokens(0);
    setErrorDetail(null);
    setStatus("planning");
    setActiveTab("workflow");            // 切到工作流 Tab 看进度
    setStartedAt(Date.now());
    cancelledRef.current = false;
    setTaskRows([]);                     // 清空任务清单
    setIntentMeta({});

    const init: Record<string, SpecialistRuntime> = {};
    for (const a of userSpecialists) {
      init[a.name] = { text: "", status: "idle", process: [] };
    }
    setSpecialists(init);

    // 直接通过裸 WebSocket 调 /ws/scenario（connectScenario 内部不支持 mode=workflow + session_id，
    // 这里用 raw WebSocket）
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/scenario`);
    let cancelledByClient = false;

    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: "start",
        request: userRequest,
        mode: "workflow",
        session_id: sessionId,
        incremental,  // S5-E — 增量更新模式（追问场景）
        // 追问时让协调者只跑 report，做增量报告
        stages: incremental ? ["report"] : undefined,
      }));
    };

    ws.onmessage = (msg) => {
      let ev: any;
      try { ev = JSON.parse(msg.data); } catch { return; }
      if (cancelledByClient) return;
      handleWorkflowEvent(ev);
    };

    ws.onclose = () => {
      scenarioRef.current = null;
    };
    ws.onerror = () => {
      if (!cancelledByClient) {
        setErrorDetail("WebSocket 错误（见 devtools）");
        setStatus("error");
      }
    };

    scenarioRef.current = {
      ws: ws as any,
      cancel: () => {
        cancelledByClient = true;
        try { ws.send(JSON.stringify({ type: "cancel" })); } catch { /* */ }
        try { ws.close(1000, "client cancel"); } catch { /* */ }
      },
    } as any;
  }

  // S2 — 处理 workflow 事件
  function handleWorkflowEvent(ev: any) {
    if (cancelledRef.current) return;
    switch (ev.type) {
      case "scenario.start": {
        setStatus("running");
        setIntentMeta({
          round: ev.round,
          intent: ev.intent,
          stages: ev.stages,
        });
        // 预填 task rows（pending）
        if (Array.isArray(ev.stages)) {
          setTaskRows((cur) => {
            const map = new Map(cur.map((r) => [r.stage, r]));
            const out: TaskRow[] = [];
            for (const stage of ev.stages) {
              const existing = map.get(stage);
              if (existing) {
                out.push({ ...existing, status: "pending" });
              } else {
                out.push({
                  stage,
                  label: stageLabel(stage),
                  mode: stageMode(stage),
                  agents: stageAgents(stage),
                  status: "pending",
                  agentSteps: [],
                });
              }
            }
            return out;
          });
        }
        break;
      }
      case "stage.start": {
        setTaskRows((rows) => rows.map((r) =>
          r.stage === ev.stage
            ? { ...r, status: "running", startTs: ev.ts, mode: ev.mode, label: ev.label || r.label, agents: ev.agents || r.agents }
            : r
        ));
        // 同步 specialistHistories（首页动态刷新 + timeline tab 都依赖它）
        // 关键修复：原代码只更新 `specialists` (legacy P3.3 状态，没人用)，
        // 导致主页卡片一直显示 idle，specialist timeline 也是空的。
        // 这里改用 specialistHistories（P7.A 单一真相，home 卡片 + timeline
        // tab 都从它派生）。
        if (Array.isArray(ev.agents)) {
          for (const a of ev.agents) {
            setSpecialistHistories((h) => appendRunningTurn(h, newRunningTurn(
              a, "scenario", query ?? "", ev.ts,
            )));
          }
        }
        break;
      }
      case "agent.start": {
        setTaskRows((rows) => rows.map((r) => {
          if (r.stage !== ev.stage) return r;
          const existing = r.agentSteps.find((s) => s.name === ev.name && s.status === "running");
          if (existing) return r;
          return {
            ...r,
            agentSteps: [
              ...r.agentSteps,
              { name: ev.name, stage: ev.stage, status: "running", text: "", toolCount: 0, ts: ev.ts },
            ],
          };
        }));
        break;
      }
      case "agent.token": {
        setTaskRows((rows) => rows.map((r) => {
          if (r.stage !== ev.stage) return r;
          return {
            ...r,
            agentSteps: r.agentSteps.map((s) =>
              s.name === ev.name ? { ...s, text: s.text + ev.delta } : s
            ),
          };
        }));
        // 同步 specialistHistories — 主页卡片 + timeline tab 都靠它
        setSpecialistHistories((h) => appendTokenDelta(h, ev.name, ev.delta));
        // E2 + S4-E — report stage 的 token 流到综合报告（"报告"tab 实时显示）。
        // S4-E: 第一次 token 不再强制跳到报告 tab，只 toast 提示，避免打断用户
        // 在主页/工作流 tab 观察 4 个智能体卡片的过程。
        if (ev.stage === "report") {
          setSynthesisText((s) => s + ev.delta);
          if (!reportStartedRef.current) {
            reportStartedRef.current = true;
            setStatus("synthesizing");
            const onReport = activeTab === "report" || activeTab === "workflow" || activeTab === "home";
            if (onReport) {
              setActiveTab("report");     // 用户当前在观察 tab 时，自动切到报告看流式
            } else {
              setToast("📋 报告已开始生成，完成后自动汇总到此 Tab");
            }
          }
        }
        setTokens((n) => n + 1);
        break;
      }
      case "agent.tool_call": {
        setTaskRows((rows) => rows.map((r) => {
          if (r.stage !== ev.stage) return r;
          return {
            ...r,
            agentSteps: r.agentSteps.map((s) =>
              s.name === ev.name ? { ...s, toolCount: s.toolCount + 1 } : s
            ),
          };
        }));
        // 同步 specialistHistories（process 步骤）
        setSpecialistHistories((h) => appendProcessStep(h, ev.name, {
          id: ev.tool_id,
          tool_name: ev.tool_name,
          tool_input: ev.tool_input,
          status: "running",
          ts: ev.ts,
        }));
        break;
      }
      case "agent.tool_result": {
        if (ev.tool_id) {
          setSpecialistHistories((h) => markProcessStep(
            h, ev.name, ev.tool_id, ev.output, ev.is_error,
          ));
        }
        break;
      }
      case "agent.done": {
        setTaskRows((rows) => rows.map((r) => {
          if (r.stage !== ev.stage) return r;
          return {
            ...r,
            agentSteps: r.agentSteps.map((s) =>
              s.name === ev.name ? { ...s, status: "done", text: ev.text } : s
            ),
          };
        }));
        // 同步 specialistHistories（finalize 这个 agent 的当前 turn）
        setSpecialistHistories((h) => finalizeTurn(
          h, ev.name, ev.text, [], tsToMs(ev.ts),
        ));
        // E2 — report 完成时把完整文本兜底写入 synthesisText
        // （token 流可能不全 / 用户中途切 tab 错过了）
        if (ev.stage === "report" && ev.text) {
          setSynthesisText((s) => s || ev.text);
          reportStartedRef.current = false;
        }
        break;
      }
      case "agent.error": {
        setTaskRows((rows) => rows.map((r) => {
          if (r.stage !== ev.stage) return r;
          return {
            ...r,
            agentSteps: r.agentSteps.map((s) =>
              s.name === ev.name ? { ...s, status: "error" } : s
            ),
          };
        }));
        // 同步 specialistHistories（error turn）
        setSpecialistHistories((h) => errorTurn(h, ev.name, ev.detail, tsToMs(ev.ts)));
        break;
      }
      case "stage.done": {
        setTaskRows((rows) => rows.map((r) =>
          r.stage === ev.stage
            ? { ...r, status: "done", finishTs: ev.ts, detail: ev.outputs?.join(", ") }
            : r
        ));
        break;
      }
      case "stage.error": {
        setTaskRows((rows) => rows.map((r) =>
          r.stage === ev.stage
            ? { ...r, status: "error", detail: ev.detail }
            : r
        ));
        break;
      }
      case "scenario.done": {
        if (ev.status === "red_flag") {
          setStatus("done");
          setToast("🚨 红旗症状命中，诊断已终止");
        } else if (ev.status === "cancelled") {
          setStatus("idle");
        } else if (ev.status === "error") {
          setStatus("error");
          setErrorDetail(ev.detail || "workflow 错误");
        } else {
          setStatus("done");
        }
        scenarioRef.current = null;
        break;
      }
    }
  }

  // S2 — 辅助函数：stage 标签/模式/agent 列表
  function stageLabel(stage: string): string {
    const map: Record<string, string> = {
      intake: "问诊采集",
      knowledge: "知识检索",
      analysis: "智能分析",
      knowledge_analysis: "知识+分析（并行）",
      evolution: "自我进化",
      report: "最终报告",
    };
    return map[stage] ?? stage;
  }
  function stageMode(stage: string): "serial" | "parallel" {
    return stage === "knowledge_analysis" ? "parallel" : "serial";
  }
  function stageAgents(stage: string): string[] {
    const map: Record<string, string[]> = {
      intake: ["intake-specialist"],
      knowledge: ["knowledge-specialist"],
      analysis: ["analysis-specialist"],
      knowledge_analysis: ["knowledge-specialist", "analysis-specialist"],
      evolution: ["evolution-specialist"],
      report: ["team-coordinator"],
    };
    return map[stage] ?? [];
  }

  // P6/P7.A: send a request to the standalone /ws/specialist endpoint.
  // Now appends to the same `specialistHistories` used by scenarios, so
  // the timeline accumulates across both modes.
  function onSendSpecialist(q: string, images?: ImageAttachment[]) {
    if (specialistRef.current) return;          // guard: don't double-send
    const agent = userSpecialists.find((a) => a.name === activeTab);
    if (!agent) return;
    cancelledSpecRef.current = false;

    let fullRequest = q;
    if (images && images.length > 0) {
      for (const img of images) {
        if (img.ocrText) {
          fullRequest += `\n\n[图片 ${img.name} 的 OCR 识别结果]\n${img.ocrText}`;
        }
      }
    }

    // P7.A — append a running Turn at send time so the timeline is
    // immediately visible. The first server event (specialist.start) will
    // not double-append because the runner only emits `text` / `tool_call`
    // / `done` from here on (the `specialist.start` from /ws/specialist
    // does NOT have a matching `specialist.start` server event the
    // frontend can react to — it comes from the same `start` ack only on
    // /ws/scenario; here we treat the local send as the start).
    setSpecialistHistories((h) => appendRunningTurn(h, newRunningTurn(
      agent.name, "standalone", fullRequest, Date.now() / 1000,
    )));
    const handle = connectSpecialist(agent.name, fullRequest, (ev: SpecialistEvent) => {
      if (cancelledSpecRef.current) return;
      switch (ev.type) {
        case "specialist.token":
          setSpecialistHistories((h) => appendTokenDelta(h, agent.name, ev.delta));
          break;
        case "specialist.tool_call":
          setSpecialistHistories((h) => appendProcessStep(h, agent.name, {
            id: ev.tool_id,
            tool_name: ev.tool_name,
            tool_input: ev.tool_input,
            status: "running",
            ts: ev.ts,
          }));
          break;
        case "specialist.tool_result":
          setSpecialistHistories((h) => markProcessStep(
            h, agent.name, ev.tool_id, ev.output, ev.is_error,
          ));
          break;
        case "specialist.done":
          setSpecialistHistories((h) => finalizeTurn(
            h, agent.name, ev.text, ev.process ?? [], tsToMs(ev.ts),
          ));
          break;
        case "specialist.error":
          setSpecialistHistories((h) => errorTurn(
            h, agent.name, ev.detail, tsToMs(ev.ts),
          ));
          break;
        case "cleared":
          // Server told us it just cleared this agent's history. Wipe
          // our local copy too so the next render matches.
          setSpecialistHistories((h) => ({ ...h, [agent.name]: [] }));
          break;
      }
      if (ev.type === "specialist.done" || ev.type === "specialist.error") {
        specialistRef.current = null;
      }
    });
    specialistRef.current = handle;
  }

  function onCancelSpecialist() {
    if (!specialistRef.current) return;
    cancelledSpecRef.current = true;
    specialistRef.current.cancel();
    specialistRef.current = null;
    // Mark the in-flight turn as idle (not error — the user cancelled).
    setSpecialistHistories((h) => updateLastRunning(h, activeTab, (t) => ({
      ...t,
      status: "done",
      finishedTs: Date.now(),
    })));
  }

  // P7.A — clear the active specialist's history. Two paths fire in
  // parallel: WS `cleared` (live, from the running connection) and
  // DELETE REST (idempotent fallback). Either one is enough; both reset
  // our local histories state.
  //
  // P3: open a confirm dialog first — the wipe is irreversible (no undo)
  // and the user might misclick the trash icon on the wrong tab.
  function onClearSpecialistHistory() {
    if (!activeTab || activeTab === "overview" || activeTab === "final") return;
    setPendingClearHistory(activeTab);
  }

  function performClearHistory() {
    const name = pendingClearHistory;
    if (!name) return;
    setPendingClearHistory(null);
    // Send via the live WS (if connected) AND via REST — both end up
    // resetting the same server-side list. Idempotent.
    specialistRef.current?.clear();
    void apiClearHistory(name);
    setSpecialistHistories((h) => ({ ...h, [name]: [] }));
    setToast(`已清空 ${name} 的对话历史`);
  }

  function onSaved(a: Agent) {
    setEditor({ kind: "closed" });
    setSelected(a.name);
    setPanelOpen(false);   // P4 — close the right panel after a save
    setToast(`已保存: ${a.name}`);
    reload();
  }

  function onSelectAgent(name: string) {
    setSelected(name);
    setActiveTab(name);
  }

  function onEditAgent(name: string) {
    const a = agents.find((x) => x.name === name);
    if (!a) return;
    setSelected(name);
    setEditor({ kind: "edit", agent: a });
  }

  function onAddAgent() {
    setEditor({ kind: "create" });
  }

  async function onConfirmDelete() {
    if (!pendingDelete) return;
    const name = pendingDelete.name;
    setPendingDelete(null);
    try {
      await api.deleteAgent(name);
      setToast(`已删除: ${name}`);
      if (selected === name) setSelected(null);
      await reload();
    } catch (e) {
      if (e instanceof ApiError) setToast(`删除失败: ${e.detail}`);
      else setToast(`删除失败: ${String(e)}`);
    }
  }

  async function onSkillsChange(newSkills: string[]) {
    if (!selectedAgent) return;
    if (savingSkillsFor) return;     // ignore while a save is in flight
    const name = selectedAgent.name;
    setSavingSkillsFor(name);
    try {
      await api.updateAgent(name, {
        ...agentToWritePayload(selectedAgent),
        skills: newSkills,
      });
      await reload();
      setToast(`已更新 ${name} 的技能`);
    } catch (e) {
      if (e instanceof ApiError) setToast(`更新失败: ${e.detail}`);
      else setToast(`更新失败: ${String(e)}`);
    } finally {
      setSavingSkillsFor(name);
      setSavingSkillsFor(null);
    }
  }

  // P7.A — "any specialist busy" is computed from the histories' last turn,
  // not from a separate `specialistRun` state.
  const isSpecialistBusy = (() => {
    const t = activeTab;
    if (!t || t === "overview" || t === "final") return false;
    const turns = specialistHistories[t];
    if (!turns || turns.length === 0) return false;
    return turns[turns.length - 1].status === "running";
  })();
  const isScenarioBusy = status !== "idle" && status !== "done" && status !== "error";
  const activeIsSpecialist = userSpecialists.some((a) => a.name === activeTab);

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100vh",
      overflow: "hidden",
      background: "var(--bg)",
    }}>
      <TopBar />

      {error && (
        <div style={{
          padding: "8px 20px",
          background: "var(--err)",
          color: "#ffffff",
          fontSize: 12,
        }}>
          ⚠ 加载后端失败: {error}
        </div>
      )}

      {toast && (
        <div
          onClick={() => setToast(null)}
          style={{
            position: "fixed",
            top: 56, left: "50%",
            transform: "translateX(-50%)",
            background: "var(--text)",
            color: "#ffffff",
            padding: "8px 18px",
            borderRadius: 6,
            fontSize: 12,
            cursor: "pointer",
            boxShadow: "0 4px 16px rgba(15, 23, 42, 0.25)",
            zIndex: 2000,
          }}
        >
          {toast}
        </div>
      )}

      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* S5-A.1 — 左侧 TaskPanel 已删除（与诊断工作流 tab 内容重复）。
            WorkflowPane 在「诊断工作流」tab 内展示 stage 进度。 */}
        <ScenarioView
          query={query}
          status={status}
          errorDetail={errorDetail}
          tokens={tokens}
          specialists={userSpecialists}
          specialistRuntimes={specialistRuntimes}
          specialistHistories={specialistHistories}
          activeTab={activeTab}
          synthesisText={synthesisText}
          onTabChange={setActiveTab}
          onSend={onSend}
          onSendSpecialist={onSendSpecialist}
          onCancelSpecialist={onCancelSpecialist}
          onClearSpecialistHistory={onClearSpecialistHistory}
          onCancel={onCancelScenario}
          onSelectAgent={onSelectAgent}
          onEditAgent={onEditAgent}
          onAddAgent={onAddAgent}
          selectedAgentName={selected}
          isSpecialistBusy={isSpecialistBusy}
          isScenarioBusy={isScenarioBusy}
          activeIsSpecialist={activeIsSpecialist}
          onJumpToKnowledge={onJumpToKnowledge}
          knowledgeFocus={knowledgeFocus}
          activeSessionId={activeSessionId}
          taskRows={taskRows}
          intentMeta={intentMeta}
        />
        {/* 整改方案 §A6: DetailPanel 已并入"团队管理" Tab (TeamPane)，
            右侧不再保留折叠条。detailPanelRef / panelOpen 仍存在以兼容
            useOutsideClick 的旧订阅，但视觉上不再渲染。 */}
      </div>

      {editor.kind !== "closed" && (
        <AgentEditor
          mode={editor.kind}
          initial={editor.kind === "edit" ? editor.agent : null}
          skills={skills}
          onClose={() => setEditor({ kind: "closed" })}
          onSaved={onSaved}
        />
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="删除智能体?"
          message={`确定要删除 "${pendingDelete.name}" 吗?\n\n此操作将删除 ~/.openharness/agents/${pendingDelete.name}.md,不可撤销。`}
          confirmLabel="删除"
          danger
          onConfirm={onConfirmDelete}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      {pendingClearHistory && (
        <ConfirmDialog
          title="清空对话历史?"
          message={`确定要清空 "${pendingClearHistory}" 的对话历史吗?\n\n所有 turn(包括 scenario 留下的回复)都会被删除,且不可撤销。`}
          confirmLabel="清空"
          danger
          onConfirm={performClearHistory}
          onCancel={() => setPendingClearHistory(null)}
        />
      )}

      {/* 整改方案 §C3 — 问诊弹窗 */}
      {intakeOpen && (
        <QuestionDialog
          onClose={() => setIntakeOpen(false)}
          onCompleted={(result) => {
            setIntakeOpen(false);
            if (result.kind === "ready" && result.sessionId) {
              setActiveSessionId(result.sessionId);
              startWorkflow(result.userRequest, result.sessionId);
            } else if (result.kind === "red_flag") {
              setStatus("done");
              setToast("🚨 已检测到红旗症状，请立即拨打 120");
            } else {
              setToast("已取消诊断");
            }
            useIntake.getState().reset();
          }}
        />
      )}
    </div>
  );
}
