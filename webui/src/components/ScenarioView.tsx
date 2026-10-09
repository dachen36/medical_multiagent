// Middle pane: scenario runtime.
// 整改方案 §A1 — 顶层导航 Tab 重命名
// 旧: 团队总览 + 4×specialist + 综合报告
// 新: 主页 / 诊断工作流 / 报告 / 知识库 / 团队管理
//   - 主页    = 团队总览 + 数据总览（常驻，智能体 work 时不刷掉）
//   - 工作流  = 问诊 + 编排中面板（S2 阶段实施）
//   - 报告    = 综合报告 + 系统自评（S4 阶段实施）
//   - 知识库  = MetaNotebook 集成占位（S4 阶段实施）
//   - 团队管理 = 替代原右侧 DetailPanel 的 agent CRUD
//
// TabId 类型为这些固定字符串。specialist detail tab 在本期暂时保留
//（通过 setActiveTab(agent.name) 直接打开）；S2 起会被"诊断工作流"内
// 的子面板替代。
//
// Header strip: status badge + request echo + token counter + cancel.
// The InputBar lives at the bottom of the panel.

import { useEffect, useMemo, useRef, useState } from "react";
import type { Agent } from "../types";
import { displayName } from "../types";
import { colorToVar } from "./AgentCard";
import { AgentIcon } from "./AgentIcon";
import { InputBar } from "./InputBar";
import { Markdown } from "./Markdown";
import { HomePane, hasAnySpecialistHistory, type SpecialistRuntime } from "./HomePane";
import { TeamPane } from "./TeamPane";
import { WorkflowPane } from "./WorkflowPane";
import { KnowledgeBase } from "./KnowledgeBase";
import type { TaskRow } from "./TaskRow";
import type { ProcessStep, Turn } from "../api/client";

type Status = "idle" | "planning" | "running" | "synthesizing" | "done" | "error";
type CardStatus = "idle" | "running" | "done" | "error";

export type TabId = "home" | "workflow" | "report" | "knowledge" | "team" | string;  // string = agent.name (S2 起被废弃)

/** 顶层 5 个固定 Tab 的字面量，便于类型安全引用。 */
export type TopTabId = "home" | "workflow" | "report" | "knowledge" | "team";
export const TOP_TABS: ReadonlyArray<{ id: TopTabId; label: string }> = [
  { id: "home",      label: "主页" },
  { id: "workflow",  label: "诊断工作流" },
  { id: "report",    label: "最终报告" },
  { id: "knowledge", label: "知识库" },
  { id: "team",      label: "团队管理" },
];

// SpecialistRuntime 类型已迁到 HomePane.tsx（整改方案 §A4：智能体动态刷新
// 接入到主页，不再只用于 OverviewPane）。这里保留 re-export 以便 App.tsx
// 等外部引用继续工作。
export type { SpecialistRuntime } from "./HomePane";

const STATUS_LABELS: Record<Status, string> = {
  idle:        "空闲",
  planning:    "规划中",
  running:     "运行中",
  synthesizing:"汇总中",
  done:        "完成",
  error:       "出错",
};

interface Props {
  query: string | null;
  status: Status;
  errorDetail?: string | null;
  tokens: number;
  /** User specialist agents (excludes the coordinator). */
  specialists: Agent[];
  /** Per-specialist runtime state, keyed by agent.name. Derived from the
   *  latest turn in `specialistHistories[name]`. Used by the Overview cards. */
  specialistRuntimes: Record<string, SpecialistRuntime>;
  /** P7.A — full conversation timeline per agent. The specialist tab
   *  renders ALL turns (oldest at top, latest at bottom), not just the
   *  latest one, so users can scroll back through multi-turn history
   *  and see context from prior scenarios. */
  specialistHistories: Record<string, Turn[]>;
  /** Final synthesis text (concatenation of the 4 specialist outputs). */
  synthesisText: string;
  activeTab: TabId;
  onTabChange: (t: TabId) => void;
  /** Scenario mode: dispatch a multi-domain request. */
  onSend: (q: string) => void;
  /** P6: specialist mode: send to /ws/specialist for the active specialist. */
  onSendSpecialist?: (q: string) => void;
  /** P6: cancel the active specialist run. */
  onCancelSpecialist?: () => void;
  /** P6: clear server-side conversation history for the active specialist. */
  onClearSpecialistHistory?: () => void;
  onCancel?: () => void;
  /** P6: clicked a card → jump to that specialist tab (was: open DetailPanel in P4). */
  onSelectAgent?: (name: string) => void;
  /** P6: clicked the card's ✎ edit button (or specialist tab header's ✎). */
  onEditAgent?: (name: string) => void;
  /** P4 — clicked the "+ 添加新智能体" button. App should open the create modal. */
  onAddAgent?: () => void;
  /** P4 — the name of the currently selected agent (for card highlight). */
  selectedAgentName?: string | null;
  /** P6 — passed down so the InputBar can be disabled while a specialist is running. */
  isSpecialistBusy?: boolean;
  /** P6 — passed down so the InputBar can be disabled while a scenario is running. */
  isScenarioBusy?: boolean;
  /** P6 — whether the active tab is a specialist tab (drives InputBar mode). */
  activeIsSpecialist?: boolean;
  // 整改方案 §A5 — scenarioMode 在 S2 阶段不再传给 ScenarioView
  // （模式选择由 App.tsx 的 useState 直接管理，不再走 InputBar dropdown）。
  /** S4-C — 诊断工作流 tab 用的实时数据。 */
  taskRows?: TaskRow[];
  intentMeta?: { round?: number; intent?: string; stages?: string[] };
  /** S5-F.2 — 知识库面板聚焦目标。 */
  knowledgeFocus?: { type: "books" | "chapters" | "cases"; id: string } | null;
  /** S5-F.2 — 点击引用链接回调。 */
  onJumpToKnowledge?: (target: { type: "books" | "chapters" | "cases"; id: string }) => void;
  /** S5-C — 智能建议用。 */
  activeSessionId?: string | null;
}

export function ScenarioView({
  query, status, errorDetail, tokens,
  specialists, specialistRuntimes, specialistHistories, synthesisText,
  activeTab, onTabChange, onSend,
  onSendSpecialist, onCancelSpecialist, onClearSpecialistHistory,
  onCancel,
  onSelectAgent, onEditAgent, onAddAgent, selectedAgentName,
  isSpecialistBusy, isScenarioBusy, activeIsSpecialist,
  taskRows, intentMeta,
  knowledgeFocus, onJumpToKnowledge,
  activeSessionId,
}: Props) {
  // Build the ordered tab list (memoize so identity is stable across renders)
  // 整改方案 §A1: 顶层 5 个固定 Tab 在前，specialist 详情 tab 暂时保留
  // 在末尾（点击主页或团队管理的卡片跳转进入）。S2 起 specialist tab
  // 会从 TabBar 中移除，改为"诊断工作流"内的子面板。
  const tabs = useMemo(() => {
    const out: { id: TabId; label: string; color?: string }[] = TOP_TABS.map((t) => ({
      id: t.id, label: t.label,
    }));
    for (const a of specialists) {
      out.push({ id: a.name, label: displayName(a), color: colorToVar(a.color) });
    }
    return out;
  }, [specialists]);

  // P6: pick the right InputBar props for the current tab.
  const inputBarMode: "scenario" | "specialist" = activeIsSpecialist ? "specialist" : "scenario";
  const inputBarAgent = activeIsSpecialist ? activeTab : undefined;
  const inputBarDisabled = (inputBarMode === "specialist" ? isSpecialistBusy : isScenarioBusy) ?? false;
  const inputBarOnSend = inputBarMode === "specialist" ? onSendSpecialist ?? (() => {}) : onSend;
  const inputBarPlaceholder = inputBarMode === "specialist" ? undefined : "输入多域请求，按 Enter 发送...";

  return (
    <main style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      background: "var(--bg)",
    }}>
      <Header
        status={status}
        query={query}
        tokens={tokens}
        isBusy={isScenarioBusy ?? false}
        onCancel={onCancel}
        onCancelSpecialist={onCancelSpecialist}
        activeIsSpecialist={activeIsSpecialist ?? false}
        isSpecialistBusy={isSpecialistBusy ?? false}
      />
      <TabBar tabs={tabs} active={activeTab} onChange={onTabChange} />

      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {activeTab === "home" ? (
          <HomePane
            specialists={specialists}
            runtimes={specialistRuntimes}
            histories={specialistHistories}
            hasSynthesis={!!synthesisText}
            onJumpToReport={() => onTabChange("report")}
            onJumpToTeam={() => onTabChange("team")}
            onSelectAgent={onSelectAgent}
            onEditAgent={onEditAgent}
            onAddAgent={onAddAgent}
            selectedAgentName={selectedAgentName}
          />
        ) : activeTab === "workflow" ? (
          <WorkflowPane
            taskRows={taskRows ?? []}
            intentMeta={intentMeta ?? {}}
            histories={specialistHistories}
            hasSynthesis={!!synthesisText}
            onJumpToReport={() => onTabChange("report")}
            onJumpToHome={() => onTabChange("home")}
            onJumpToAgent={onSelectAgent}
          />
        ) : activeTab === "report" ? (
          <ReportPane
            status={status}
            text={synthesisText}
            errorDetail={errorDetail}
            isBusy={isScenarioBusy ?? false}
            hasHistory={hasAnySpecialistHistory(specialistHistories)}
          />
        ) : activeTab === "knowledge" ? (
          <KnowledgeBase focusTarget={knowledgeFocus ?? null} />
        ) : activeTab === "team" ? (
          <TeamPane
            specialists={specialists}
            selectedAgentName={selectedAgentName}
            onSelectAgent={onSelectAgent}
            onEditAgent={onEditAgent}
            onAddAgent={onAddAgent}
          />
        ) : (
          // Per-specialist stream tab (P7.A: timeline view of all turns)
          (() => {
            const spec = specialists.find((a) => a.name === activeTab);
            const turns = specialistHistories[activeTab] ?? [];
            return (
              <SpecialistTimeline
                agent={spec ?? null}
                turns={turns}
                isBusy={(isSpecialistBusy ?? false) || (isScenarioBusy ?? false)}
                onEdit={onEditAgent ? () => onEditAgent(activeTab) : undefined}
                onClearHistory={onClearSpecialistHistory}
                onBackHome={() => onTabChange("home")}
                onJumpToKnowledge={onJumpToKnowledge}
              />
            );
          })()
        )}
      </div>

      <InputBar
        onSend={inputBarOnSend}
        disabled={inputBarDisabled}
        placeholder={inputBarPlaceholder}
        mode={inputBarMode}
        agentName={inputBarAgent}
        activeSessionId={activeSessionId}
      />
    </main>
  );
}


// ---------------------------------------------------------------------------
// Header strip
// ---------------------------------------------------------------------------
function Header({
  status, query, tokens, isBusy, onCancel,
  onCancelSpecialist, activeIsSpecialist, isSpecialistBusy,
}: {
  status: Status;
  query: string | null;
  tokens: number;
  isBusy: boolean;
  onCancel?: () => void;
  onCancelSpecialist?: () => void;
  activeIsSpecialist: boolean;
  isSpecialistBusy: boolean;
}) {
  // P6 — when a specialist tab is active, show "独立咨询" badge + the
  // specialist cancel button instead of the scenario cancel button.
  const label = activeIsSpecialist ? "独立咨询" : "场景";
  const statusLabel = activeIsSpecialist
    ? (isSpecialistBusy ? "运行中" : status === "idle" ? "空闲" : "等待")
    : STATUS_LABELS[status];
  const statusBg = activeIsSpecialist
    ? (isSpecialistBusy ? "var(--accent)" : "var(--bg-elev)")
    : (status === "idle" ? "var(--bg-elev)" : "var(--accent)");
  const statusFg = activeIsSpecialist
    ? (isSpecialistBusy ? "#ffffff" : "var(--text-dim)")
    : (status === "idle" ? "var(--text-dim)" : "#ffffff");

  return (
    <div style={{
      padding: "10px 18px",
      borderBottom: "1px solid var(--border-soft)",
      display: "flex",
      alignItems: "center",
      gap: 12,
      fontSize: 12,
      background: "var(--bg-soft)",
      flexShrink: 0,
    }}>
      <span style={{ fontWeight: 700, letterSpacing: 1.2, color: "var(--accent)" }}>
        {label}
      </span>
      <span style={{
        padding: "2px 10px", borderRadius: 4,
        background: statusBg,
        color: statusFg,
        fontWeight: 700, fontSize: 10, letterSpacing: 1,
      }}>
        {statusLabel}
      </span>
      {query && !activeIsSpecialist && (
        <span style={{
          color: "var(--text-faint)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          flex: 1,
        }}>
          <span style={{ color: "var(--text-faint)" }}>请求: </span>
          <span style={{ color: "var(--text-dim)" }}>{query}</span>
        </span>
      )}
      {isBusy && !activeIsSpecialist && (
        <span style={{
          fontSize: 10, color: "var(--text-faint)",
          fontFamily: "ui-monospace, monospace",
        }}>
          {tokens} tokens
        </span>
      )}
      {!activeIsSpecialist && onCancel && isBusy && (
        <button onClick={onCancel} style={{
          padding: "2px 10px", fontSize: 11, color: "var(--err)",
        }}>
          取消
        </button>
      )}
      {activeIsSpecialist && onCancelSpecialist && isSpecialistBusy && (
        <button onClick={onCancelSpecialist} style={{
          padding: "2px 10px", fontSize: 11, color: "var(--err)",
        }}>
          取消
        </button>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Tab bar — driven by an array of {id, label, color?}, supports scroll
// when the tab list overflows (5+ tabs in P3.3).
// ---------------------------------------------------------------------------
function TabBar({
  tabs, active, onChange,
}: {
  tabs: { id: TabId; label: string; color?: string }[];
  active: TabId;
  onChange: (t: TabId) => void;
}) {
  return (
    <div style={{
      display: "flex",
      borderBottom: "1px solid var(--border-soft)",
      background: "var(--bg)",
      flexShrink: 0,
      overflowX: "auto",
    }}>
      {tabs.map((t) => {
        const isActive = t.id === active;
        return (
          <button
            key={t.id}
            onClick={() => onChange(t.id)}
            style={{
              padding: "9px 16px",
              fontSize: 12,
              fontWeight: isActive ? 600 : 400,
              color: isActive ? "var(--accent)" : "var(--text-dim)",
              background: "transparent",
              border: "none",
              borderBottom: isActive
                ? `2px solid ${t.color ?? "var(--accent)"}`
                : "2px solid transparent",
              borderRadius: 0,
              cursor: "pointer",
              marginBottom: -1,
              whiteSpace: "nowrap",
              transition: "color 0.12s, border-color 0.12s",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {t.color && (
              <span style={{
                display: "inline-block", width: 8, height: 8, borderRadius: "50%",
                background: t.color, opacity: isActive ? 1 : 0.45,
              }} />
            )}
            {t.label}
          </button>
        );
      })}
    </div>
  );
}




// ---------------------------------------------------------------------------
// Per-specialist stream tab (P7.A: timeline view of all turns)
// ---------------------------------------------------------------------------
function SpecialistTimeline({
  agent, turns, isBusy,
  onEdit, onClearHistory, onBackHome, onJumpToKnowledge,
}: {
  agent: Agent | null;
  /** Full chronological list of turns for this agent. */
  turns: Turn[];
  isBusy: boolean;
  /** P6 — open the editor modal for this agent. */
  onEdit?: () => void;
  /** P6 — clear server-side conversation history. */
  onClearHistory?: () => void;
  /** 整改方案 §A1 — 头部加一个"返回主页"按钮，避免点进 specialist tab 后迷路。 */
  onBackHome?: () => void;
  /** S5-F.2 — 点击引用链接跳知识库面板 */
  onJumpToKnowledge?: (target: { type: "books" | "chapters" | "cases"; id: string }) => void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;

  // Auto-scroll the body to the bottom as new tokens arrive
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [turns]);

  if (!agent) {
    return (
      <div style={{
        flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
        color: "var(--text-faint)", fontSize: 12,
      }}>
        未知智能体
      </div>
    );
  }

  const color = colorToVar(agent.color);
  // Latest turn is "live" if it's still running
  const isLive = lastTurn?.status === "running";
  const totalChars = turns.reduce((acc, t) => acc + t.text.length, 0);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <SpecialistHeader
        agent={agent}
        color={color}
        status={lastTurn?.status === "running" ? "running"
             : lastTurn?.status === "error"   ? "error"
             : turns.length > 0 ? "done" : "idle"}
        textLen={totalChars}
        turnCount={turns.length}
        onEdit={onEdit}
        onClearHistory={turns.length > 0 ? onClearHistory : undefined}
        onBackHome={onBackHome}
      />

      <div
        ref={bodyRef}
        style={{
          flex: 1, overflow: "auto",
          padding: "16px 24px",
          fontSize: 13, lineHeight: 1.7,
          color: "var(--text)",
          display: "flex", flexDirection: "column",
        }}
      >
        {turns.length === 0 ? (
          <div style={{
            flex: 1, minHeight: 240,
            display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center",
            color: "var(--text-faint)", fontSize: 12,
            padding: 24, textAlign: "center",
          }}>
            <div style={{ color, marginBottom: 12 }}>
              <AgentIcon name={agent.name} size={48} />
            </div>
            <div style={{ color: "var(--text-dim)", fontWeight: 500, marginBottom: 4 }} title={agent.name}>
              {displayName(agent)}
            </div>
            <div style={{ fontSize: 11 }}>
              在下方输入提问，开始多轮对话
            </div>
          </div>
        ) : (
          turns.map((turn, idx) => (
            <TurnCard
              key={turn.id}
              turn={turn}
              color={color}
              isLive={isLive && idx === turns.length - 1}
              onJumpToKnowledge={onJumpToKnowledge}
            />
          ))
        )}
        {/* spacer so the last turn's pulsing cursor doesn't get clipped */}
        {isLive && <div style={{ height: 24 }} />}
      </div>
    </div>
  );
}


/** P7.A: one turn card = one user question + assistant response (with
 *  optional 思考过程 region). Sits inside the SpecialistTimeline.
 *
 *  Layout (P1 update): the user's query is now a dedicated quoted block
 *  spanning the full card width — long queries stay readable, no more
 *  240px italic truncation on the right. "USER" / "ASSISTANT" labels make
 *  the dialog structure scannable when scrolling through many turns. */
function TurnCard({
  turn, color, isLive, onJumpToKnowledge,
}: {
  turn: Turn;
  color: string;
  isLive: boolean;
  /** S5-F.2 — 点击引用链接跳知识库面板 */
  onJumpToKnowledge?: (target: { type: "books" | "chapters" | "cases"; id: string }) => void;
}) {
  const duration = turn.finishedTs && turn.ts
    ? Math.max(0, Math.round((turn.finishedTs - turn.ts) / 1000))
    : null;

  // S5-F.2 — 检测 turn.text 里的引用（书名《xxx》、CR-xxx 临床规则）
  const refs = onJumpToKnowledge ? extractReferences(turn.text) : [];

  return (
    <div style={{
      marginBottom: 18,
      padding: "10px 14px",
      border: `1px solid var(--border-soft)`,
      borderRadius: 8,
      background: "var(--bg)",
    }}>
      {/* turn meta row: time + source + status (no more request here) */}
      <div style={{
        display: "flex", gap: 8, alignItems: "center",
        fontSize: 11, color: "var(--text-faint)",
        marginBottom: 8,
      }}>
        <span>{formatTime(turn.ts)}</span>
        <SourceBadge source={turn.source} />
        {isLive && (
          <span style={{ color: "var(--accent)" }}>● 进行中</span>
        )}
        {turn.status === "error" && (
          <span style={{ color: "var(--err)" }}>● 出错</span>
        )}
        {duration !== null && (
          <span style={{ color: "var(--text-faint)" }}>
            · 用时 {duration}s
          </span>
        )}
      </div>

      {/* USER block: full-width, preserved line breaks, no truncation */}
      <div style={{
        padding: "8px 12px",
        background: "var(--bg-soft)",
        borderLeft: `3px solid ${color}`,
        borderRadius: 4,
        fontSize: 13,
        lineHeight: 1.6,
        color: "var(--text)",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        marginBottom: 10,
      }}>
        <div style={{
          fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
          color: "var(--text-faint)", marginBottom: 4,
        }}>
          USER
        </div>
        {turn.request || <span style={{ color: "var(--text-faint)" }}>(空)</span>}
      </div>

      {/* 过程 region (collapsible) */}
      {turn.process.length > 0 && (
        <details open style={{
          background: "var(--bg-soft)",
          border: "1px solid var(--border-soft)",
          borderRadius: 6,
          padding: 10,
          marginBottom: 10,
        }}>
          <summary style={{
            fontSize: 11, fontWeight: 600, color: "var(--text-dim)",
            cursor: "pointer", userSelect: "none",
          }}>
            思考过程 · {turn.process.length} 步
          </summary>
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
            {turn.process.map((step) => (
              <ProcessStepRow key={step.id} step={step} color={color} />
            ))}
          </div>
        </details>
      )}

      {/* ASSISTANT label + result region */}
      <div style={{
        fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
        color: "var(--text-faint)", marginBottom: 4,
      }}>
        ASSISTANT
      </div>
      {turn.text ? (
        <div>
          <Markdown text={turn.text} className="md-body" />
          {/* S5-F.2 — 检测到的引用，点击跳知识库 */}
          {refs.length > 0 && (
            <div style={{
              marginTop: 10, paddingTop: 8,
              borderTop: "1px dashed var(--border-soft)",
              display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center",
            }}>
              <span style={{ fontSize: 10, color: "var(--text-faint)" }}>📎 引用：</span>
              {refs.map((ref, idx) => (
                <button
                  key={idx}
                  onClick={(e) => { e.stopPropagation(); onJumpToKnowledge!(ref); }}
                  style={{
                    padding: "2px 8px", fontSize: 10, fontFamily: "ui-monospace, monospace",
                    background: "var(--accent-soft)", color: "var(--accent-dim)",
                    border: "1px solid var(--accent)", borderRadius: 12,
                    cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 3,
                  }}
                  title={`跳到知识库：${ref.type}/${ref.id}`}
                >
                  <span style={{ fontSize: 9 }}>
                    {ref.type === "books" ? "📘" : ref.type === "chapters" ? "📑" : "📐"}
                  </span>
                  {ref.label}
                  <span style={{ fontSize: 8, opacity: 0.6 }}>→</span>
                </button>
              ))}
            </div>
          )}
          {isLive && (
            <span style={{
              display: "inline-block",
              width: 7, height: 14, marginLeft: 2,
              background: color,
              verticalAlign: "text-bottom",
              animation: "pulse 0.9s ease-in-out infinite",
            }} />
          )}
        </div>
      ) : isLive ? (
        <span style={{ color: "var(--text-faint)" }}>…</span>
      ) : null}

      {/* error banner */}
      {turn.status === "error" && (
        <div style={{
          marginTop: 10, padding: 8, fontSize: 11,
          color: "#991b1b", background: "#fee2e2", borderRadius: 6,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          fontFamily: "ui-monospace, monospace",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            ⚠ 该 specialist 调用失败
          </div>
          {turn.errorDetail || "(no detail)"}
        </div>
      )}
    </div>
  );
}


/** P7.A: badge showing where a turn came from. */
function SourceBadge({ source }: { source: Turn["source"] }) {
  const label = source === "scenario" ? "场景" : "独立";
  const color = source === "scenario" ? "var(--accent)" : "var(--text-dim)";
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 3,
      background: color, color: "#ffffff",
      fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
    }}>
      {label}
    </span>
  );
}


/** P7.A: format ms-epoch to "HH:MM:SS" for the turn header. */
function formatTime(tsMs: number): string {
  const d = new Date(tsMs);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}


// ---------------------------------------------------------------------------
// P6: per-specialist header — same as before but adds ✎ edit and 🗑 clear buttons
// ---------------------------------------------------------------------------
function SpecialistHeader({
  agent, color, status, textLen, turnCount, onEdit, onClearHistory, onBackHome,
}: {
  agent: Agent;
  color: string;
  status: CardStatus;
  textLen: number;
  turnCount?: number;
  onEdit?: () => void;
  onClearHistory?: () => void;
  /** 整改方案 §A1 — "返回主页"快捷入口。 */
  onBackHome?: () => void;
}) {
  return (
    <div style={{
      padding: "8px 18px",
      borderBottom: "1px solid var(--border-soft)",
      display: "flex", alignItems: "center", gap: 10,
      background: "var(--bg-soft)",
      flexShrink: 0,
    }}>
      {onBackHome && (
        <button
          onClick={onBackHome}
          title="返回主页"
          style={{
            padding: "1px 8px", fontSize: 11, lineHeight: 1.2,
            color: "var(--text-dim)",
          }}
        >
          ← 主页
        </button>
      )}
      <span style={{ color, display: "inline-flex" }}>
        <AgentIcon name={agent.name} size={20} />
      </span>
      <span style={{ fontWeight: 600, fontSize: 13, color: "var(--text)" }} title={agent.name}>
        {displayName(agent)}
      </span>
      {/* 整改方案 §A1: 旧的 CardStatusBadge 已随 SpecialistCard 一起迁到
          HomePane.tsx（仅 HomePane 内的团队总览卡片需要）。Specialist
          时间线用 SpecialistHeader 内联的更简洁样式。 */}
      <HeaderStatusBadge status={status} />
      {turnCount !== undefined && turnCount > 0 && (
        <span style={{
          fontSize: 10, color: "var(--text-faint)",
          fontFamily: "ui-monospace, monospace",
        }}>
          · {turnCount} 轮
        </span>
      )}
      <span style={{
        marginLeft: "auto", fontSize: 10, color: "var(--text-faint)",
        fontFamily: "ui-monospace, monospace",
      }}>
        {textLen} 字
      </span>
      {onEdit && (
        <button
          onClick={onEdit}
          title="编辑"
          style={{ padding: "1px 8px", fontSize: 11, lineHeight: 1.2 }}
        >
          ✎
        </button>
      )}
      {onClearHistory && (
        <button
          onClick={onClearHistory}
          title="清空对话历史"
          style={{ padding: "1px 8px", fontSize: 11, lineHeight: 1.2, color: "var(--err)" }}
        >
          🗑
        </button>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// P6: process step row — one tool call + its result
// ---------------------------------------------------------------------------
function ProcessStepRow({ step, color }: { step: ProcessStep; color: string }) {
  const statusColor = step.is_error
    ? "var(--err)"
    : step.status === "running"
    ? "var(--accent)"
    : "var(--ok)";
  const icon = step.status === "running" ? "⚙" : step.is_error ? "✗" : "✓";

  return (
    <div style={{
      fontSize: 11,
      fontFamily: "ui-monospace, monospace",
      border: `1px solid ${statusColor}`,
      borderRadius: 6,
      padding: 8,
      background: "var(--bg)",
      opacity: step.status === "running" ? 0.85 : 1,
    }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ color: statusColor, fontWeight: 700, width: 12, textAlign: "center" }}>{icon}</span>
        <span style={{ color: statusColor, fontWeight: 600 }}>{step.tool_name}</span>
        <span style={{ color: "var(--text-faint)" }}>({step.id.slice(0, 8)}…)</span>
        {step.status === "running" && (
          <span style={{ color, fontSize: 10, marginLeft: 4 }}>running</span>
        )}
      </div>
      <div style={{ marginTop: 4, color: "var(--text-dim)" }}>
        <span style={{ color: "var(--text-faint)" }}>input: </span>
        <code style={{ fontSize: 11, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {JSON.stringify(step.tool_input)}
        </code>
      </div>
      {step.output !== undefined && (
        <div style={{ marginTop: 4, color: "var(--text-dim)" }}>
          <span style={{ color: "var(--text-faint)" }}>output: </span>
          <span style={{
            whiteSpace: "pre-wrap", wordBreak: "break-word",
            color: step.is_error ? "var(--err)" : "var(--text-dim)",
          }}>
            {step.output.length > 800 ? step.output.slice(0, 800) + "…(+" + (step.output.length - 800) + " chars)" : step.output}
          </span>
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// 整改方案 §A1: 报告 Tab — 渲染综合报告 + 系统自评
// S1 阶段：仅做综合报告的展示壳，S4 阶段接"双报告"（综合 + 自评）
// ---------------------------------------------------------------------------
function ReportPane({
  status, text, errorDetail, isBusy, hasHistory,
}: {
  status: Status;
  text: string;
  errorDetail?: string | null;
  isBusy: boolean;
  hasHistory: boolean;
}) {
  const [tab, setTab] = useState<"report" | "self">("report");

  // E3 — 按 ---META_REPORT_SPLIT--- 把协调者的输出拆成两段
  // 没有分隔符时（旧模式 / 拼接报告）整段当综合报告，自评留空走占位。
  const SPLIT = "---META_REPORT_SPLIT---";
  let reportText = text;
  let selfText = "";
  const splitIdx = text.indexOf(SPLIT);
  if (splitIdx !== -1) {
    reportText = text.slice(0, splitIdx).trim();
    selfText = text.slice(splitIdx + SPLIT.length).trim();
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{
        display: "flex", gap: 0, padding: "0 24px",
        borderBottom: "1px solid var(--border-soft)",
        background: "var(--bg-soft)", flexShrink: 0,
      }}>
        <SubTab
          active={tab === "report"}
          onClick={() => setTab("report")}
          label="最终报告"
        />
        <SubTab
          active={tab === "self"}
          onClick={() => setTab("self")}
          label="系统自评"
        />
      </div>
      {tab === "report" ? (
        <FinalReportBody
          status={status} text={reportText} errorDetail={errorDetail} isBusy={isBusy}
        />
      ) : (
        <SelfAssessmentBody hasHistory={hasHistory} liveText={selfText} />
      )}
    </div>
  );
}

function SubTab({
  active, onClick, label,
}: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "9px 14px", fontSize: 12,
        fontWeight: active ? 600 : 400,
        color: active ? "var(--accent)" : "var(--text-dim)",
        background: "transparent",
        border: "none",
        borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
        borderRadius: 0, cursor: "pointer",
        marginBottom: -1,
      }}
    >
      {label}
    </button>
  );
}

function FinalReportBody({
  status, text, errorDetail, isBusy,
}: {
  status: Status;
  text: string;
  errorDetail?: string | null;
  isBusy: boolean;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [text, status]);

  if (status === "idle" && !text) {
    return (
      <div style={{
        flex: 1,
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "var(--text-faint)", fontSize: 13,
        padding: 32, textAlign: "center", overflow: "auto",
      }}>
        <div>
          <div style={{
            fontSize: 56, marginBottom: 14, color: "var(--accent)",
            opacity: 0.6,
            filter: "drop-shadow(0 0 8px var(--accent-glow))",
          }}>
            ⚡
          </div>
          <div style={{ color: "var(--text-dim)", fontWeight: 500 }}>
            报告将在综合完成后显示
          </div>
          <div style={{ fontSize: 11, marginTop: 8, color: "var(--text-faint)" }}>
            <em>当前工作流：4 阶段编排（问诊 → 检索/分析 → 自进化 → 综合）</em>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={bodyRef}
      style={{
        flex: 1, overflow: "auto",
        padding: "20px 24px",
        fontSize: 13, lineHeight: 1.7,
        color: "var(--text)",
      }}
    >
      {text ? (
        <Markdown text={text} className="md-body" />
      ) : (
        isBusy ? <span style={{ color: "var(--text-faint)" }}>…</span> : null
      )}
      {status === "error" && errorDetail && (
        <div style={{
          marginTop: 16, padding: 10,
          border: "1px solid #fecaca", background: "#fee2e2",
          color: "#991b1b", borderRadius: 6, fontSize: 12,
          whiteSpace: "pre-wrap",
        }}>
          ⚠ {errorDetail}
        </div>
      )}
      {status === "done" && (
        <div style={{
          marginTop: 16, fontSize: 11, color: "var(--ok)",
          fontFamily: "-apple-system, sans-serif",
        }}>
          ✓ 综合完成 · {text.length} 字
        </div>
      )}
    </div>
  );
}

function SelfAssessmentBody({
  hasHistory, liveText,
}: {
  hasHistory: boolean;
  /** E3 — 协调者在 SPLIT 分隔符后输出的自评正文（可能为空） */
  liveText?: string;
}) {
  if (!hasHistory) {
    return (
      <div style={{
        flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
        flexDirection: "column", gap: 8,
        color: "var(--text-faint)", fontSize: 12,
        padding: 32, textAlign: "center",
      }}>
        <div style={{ fontSize: 36, opacity: 0.5 }}>📊</div>
        <div>完成至少一次诊断后，将显示系统自评与知识缺口</div>
      </div>
    );
  }

  // E4 — 自评正文优先用协调者实时生成的（liveText）。
  // 协调者没输出自评段时（旧模式 / LLM 没遵守格式），用 dashboard stats 占位。
  const body = liveText && liveText.trim().length > 20
    ? liveText
    : [
        "# 系统自评",
        "",
        "> 协调者本次未生成详细自评，以下为系统概览：",
        "",
        "## 当前系统状态",
        "- 知识库：60 教材 / 16,444 章节 / 84,307 KG 实体 / 120,193 KG 关系",
        "- 药物互作对：2,587",
        "- 累计病历：20 例 / 175 就诊记录",
        "- 进化轮次：11 · 诊断模式簇 26 · 高置信模式 2 · KG 注入 11 · 活跃规律 1",
        "",
        "## 📚 添加书籍",
        "> MetaNotebook 集成进行中，集成完成后可一键导入 PDF，",
        "> 系统将自动切片入 RAG、抽取实体入 KG、刷新盲区列表。",
      ].join("\n");

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 24px" }}>
      <Markdown text={body} className="md-body" />
    </div>
  );
}


// ---------------------------------------------------------------------------
// 整改方案 §A1 — SpecialistHeader 用的内联状态徽章（紧凑版）
// 与 HomePane 内的 CardStatusBadge 区别：放在 header 里，更小、更素。
// ---------------------------------------------------------------------------
function HeaderStatusBadge({ status }: { status: "idle" | "running" | "done" | "error" }) {
  const meta: Record<string, { label: string; bg: string; fg: string; pulse?: boolean }> = {
    idle:    { label: "空闲",  bg: "var(--bg-elev)",  fg: "var(--text-faint)" },
    running: { label: "运行中", bg: "var(--accent-soft)", fg: "var(--accent-dim)", pulse: true },
    done:    { label: "完成",  bg: "#dcfce7",         fg: "#15803d" },
    error:   { label: "出错",  bg: "#fee2e2",         fg: "#991b1b" },
  };
  const m = meta[status];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 10,
      background: m.bg, color: m.fg,
      fontSize: 10, fontWeight: 600, flexShrink: 0,
    }}>
      {m.pulse && (
        <span style={{
          width: 5, height: 5, borderRadius: "50%",
          background: m.fg,
          animation: "pulse 0.9s ease-in-out infinite",
        }} />
      )}
      {m.label}
    </span>
  );
}


// ---------------------------------------------------------------------------
// S5-F.2 — 从 agent 输出文本里识别引用（书名《xxx》、CR-xxx 临床规则）
// 返回去重后的引用列表。识别规则：
//   - 《书名》   → books tab（去匹配 _KNOWN_BOOKS）
//   - CR-xxx-yyy → cases tab（规则 id）
//   - ch.NN 章节引用不直接识别（章节 id 包含 book 前缀，命中率低，留 S5-F.3）
// ---------------------------------------------------------------------------
function extractReferences(text: string): { type: "books" | "chapters" | "cases"; id: string; label: string }[] {
  if (!text) return [];
  const seen = new Set<string>();
  const out: { type: "books" | "chapters" | "cases"; id: string; label: string }[] = [];

  // 书名 《xxx》
  const bookRe = /《([^》\n]{2,24})》/g;
  let m: RegExpExecArray | null;
  while ((m = bookRe.exec(text)) !== null) {
    const name = m[1].trim();
    // 简化匹配：直接拿 name 作 id（knowledge_api 里没暴露 id->name 反查）
    const key = `book:${name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ type: "books", id: name, label: `《${name}》` });
  }

  // 临床规则 CR-xxx（支持中文规则 id，如 CR-急性胃肠炎-6-20260601）
  // 用 (?<![A-Za-z0-9_]) 替代 \b 因为 - 不是 \w 字符
  // 用 Unicode range 一-鿿 匹配中文
  const crRe = /(?<![A-Za-z0-9_])(CR-[一-鿿A-Za-z0-9][一-鿿A-Za-z0-9-]+)/g;
  while ((m = crRe.exec(text)) !== null) {
    const cr = m[1];
    const key = `cr:${cr}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ type: "cases", id: cr, label: cr });
  }

  return out;
}
