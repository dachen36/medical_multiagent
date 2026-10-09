// CanvasShell — the viewState router for the redesigned middle pane.
//
// Owns: top header chip (query + cancel + token counter), routing between
// the four view components (Landing / Bento / Spotlight / Synthesis), the
// optional CoordinatorTrace strip, and the bottom InputBar.
//
// The shell does NOT own state — App.tsx still holds viewState, spotlight
// agent, etc. CanvasShell simply receives them as props and dispatches user
// intent (clicks, cancels) back up via callbacks.

import type { Agent } from "../../types";
import type { ViewState } from "../../types";
import type { ScenarioEvent, Turn } from "../../api/client";
import { InputBar } from "../InputBar";
import { LandingHero } from "./LandingHero";
import { BentoGrid } from "./BentoGrid";
import { SpotlightView } from "./SpotlightView";
import { SynthesisView } from "./SynthesisView";
import { CoordinatorTrace } from "./CoordinatorTrace";

type Status = "idle" | "planning" | "running" | "synthesizing" | "done" | "error";

interface Props {
  viewState: ViewState;
  // ---- specialists + history ----
  specialists: Agent[];
  specialistHistories: Record<string, Turn[]>;
  historyTurnCounts: Record<string, number>;
  // ---- runtime state ----
  status: Status;
  query: string | null;
  tokens: number;
  events: ScenarioEvent[];
  errorDetail: string | null;
  synthesisText: string;
  // ---- canvas focus ----
  spotlightAgent: string | null;
  standaloneAgent: string | null;
  /** True when synthesis.start fired while user was in spotlight — chip
   *  shows at the top until user dismisses or clicks through to synthesis. */
  synthesisReadyChip: boolean;
  // ---- coordinator mode ----
  scenarioMode: "classic" | "coordinator";
  onScenarioModeChange: (m: "classic" | "coordinator") => void;
  dispatchedAgents: Set<string>;
  // ---- intent callbacks ----
  onSendScenario: (q: string) => void;
  onSendSpecialist: (name: string, q: string) => void;
  onCancelScenario: () => void;
  onCancelSpecialist: (name: string) => void;
  onSpotlight: (name: string) => void;
  onBackToBento: () => void;
  onToSynthesis: () => void;
  onDismissSynthesisChip: () => void;
  onToggleStandalone: (name: string) => void;
  onClearHistory: (name: string) => void;
  onEditAgent: (name: string) => void;
  // ---- run-state derived ----
  isScenarioBusy: boolean;
  isSpecialistBusy: boolean;
}

export function CanvasShell({
  viewState, specialists, specialistHistories, historyTurnCounts,
  status, query, tokens, events, errorDetail, synthesisText,
  spotlightAgent, standaloneAgent, synthesisReadyChip,
  scenarioMode, onScenarioModeChange, dispatchedAgents,
  onSendScenario, onSendSpecialist,
  onCancelScenario, onCancelSpecialist,
  onSpotlight, onBackToBento, onToSynthesis, onDismissSynthesisChip,
  onToggleStandalone, onClearHistory, onEditAgent,
  isScenarioBusy, isSpecialistBusy,
}: Props) {
  // Landing has its own composition — return early
  if (viewState === "landing") {
    return (
      <main style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        background: "var(--bg)",
        position: "relative",
      }}>
        <LandingHero
          specialists={specialists}
          historyTurnCounts={historyTurnCounts}
          scenarioMode={scenarioMode}
          onScenarioModeChange={onScenarioModeChange}
          onSend={onSendScenario}
          disabled={isScenarioBusy}
        />
      </main>
    );
  }

  // InputBar mode depends on whether a standalone chat is open
  const inputMode: "scenario" | "specialist" =
    standaloneAgent && viewState === "spotlight" && spotlightAgent === standaloneAgent
      ? "specialist"
      : "scenario";
  const inputDisabled = inputMode === "specialist" ? isSpecialistBusy : isScenarioBusy;
  const inputAgentName = inputMode === "specialist" ? standaloneAgent ?? undefined : undefined;
  const inputOnSend = (q: string) => {
    if (inputMode === "specialist" && standaloneAgent) {
      onSendSpecialist(standaloneAgent, q);
    } else {
      onSendScenario(q);
    }
  };

  return (
    <main style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      background: "var(--bg)",
      position: "relative",
    }}>
      <QueryHeader
        viewState={viewState}
        status={status}
        query={query}
        tokens={tokens}
        errorDetail={errorDetail}
        synthesisReadyChip={synthesisReadyChip}
        onCancel={onCancelScenario}
        onToSynthesis={onToSynthesis}
        onDismissSynthesisChip={onDismissSynthesisChip}
      />

      {viewState === "bento" && scenarioMode === "coordinator" && (
        <div style={{ padding: "0 16px", flexShrink: 0 }}>
          <CoordinatorTrace events={events} />
        </div>
      )}

      <div style={{ flex: 1, overflow: "hidden", display: "flex" }}>
        {viewState === "bento" && (
          <BentoGrid
            specialists={specialists}
            specialistHistories={specialistHistories}
            dispatchedAgents={dispatchedAgents}
            coordinatorMode={scenarioMode === "coordinator"}
            onSpotlight={onSpotlight}
            onEdit={onEditAgent}
          />
        )}
        {viewState === "spotlight" && spotlightAgent && (
          <SpotlightView
            specialists={specialists}
            spotlightAgent={spotlightAgent}
            specialistHistories={specialistHistories}
            standaloneActive={standaloneAgent === spotlightAgent}
            onBackToBento={onBackToBento}
            onSwitch={onSpotlight}
            onToggleStandalone={() => onToggleStandalone(spotlightAgent)}
            onCancelStandalone={() => onCancelSpecialist(spotlightAgent)}
            onClearHistory={() => onClearHistory(spotlightAgent)}
            onEdit={() => onEditAgent(spotlightAgent)}
          />
        )}
        {viewState === "synthesis" && (
          <SynthesisView
            specialists={specialists}
            specialistHistories={specialistHistories}
            status={status}
            synthesisText={synthesisText}
            errorDetail={errorDetail}
            isBusy={isScenarioBusy}
            onSpotlightSpecialist={onSpotlight}
            onBackToBento={onBackToBento}
          />
        )}
      </div>

      <InputBar
        variant="footer"
        mode={inputMode === "scenario" ? "scenario" : "specialist"}
        agentName={inputAgentName}
        onSend={inputOnSend}
        disabled={inputDisabled}
        scenarioMode={scenarioMode}
        onScenarioModeChange={inputMode === "scenario" ? onScenarioModeChange : undefined}
      />
    </main>
  );
}


// ---------------------------------------------------------------------------
// Header strip with query echo + tokens + cancel
// ---------------------------------------------------------------------------
function QueryHeader({
  viewState, status, query, tokens, errorDetail,
  synthesisReadyChip, onCancel, onToSynthesis, onDismissSynthesisChip,
}: {
  viewState: ViewState;
  status: Status;
  query: string | null;
  tokens: number;
  errorDetail: string | null;
  synthesisReadyChip: boolean;
  onCancel: () => void;
  onToSynthesis: () => void;
  onDismissSynthesisChip: () => void;
}) {
  const showCancel = viewState !== "synthesis"
    && (status === "planning" || status === "running" || status === "synthesizing");

  const statusLabel =
    status === "planning"     ? "规划中" :
    status === "running"      ? "运行中" :
    status === "synthesizing" ? "汇总中" :
    status === "done"         ? "完成" :
    status === "error"        ? "出错" : "空闲";

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
      <span style={{
        padding: "2px 10px", borderRadius: 4,
        background: status === "idle" ? "var(--bg-elev)"
                  : status === "error" ? "var(--err)"
                  : status === "done"  ? "var(--ok)" : "var(--accent)",
        color: status === "idle" ? "var(--text-dim)" : "#ffffff",
        fontWeight: 700, fontSize: 10, letterSpacing: 1,
      }}>
        {statusLabel}
      </span>

      {query && (
        <span style={{
          color: "var(--text-dim)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          flex: 1, minWidth: 0,
        }} title={query}>
          <span style={{ color: "var(--text-faint)" }}>请求: </span>
          {query}
        </span>
      )}

      {!query && <span style={{ flex: 1 }} />}

      {synthesisReadyChip && viewState === "spotlight" && (
        <span
          className="synthesis-chip"
          onClick={onToSynthesis}
          title="查看综合报告"
        >
          📋 综合报告已就绪 · 查看
        </span>
      )}
      {synthesisReadyChip && viewState === "spotlight" && (
        <button
          onClick={onDismissSynthesisChip}
          title="稍后再看"
          style={{ padding: "1px 6px", fontSize: 11, lineHeight: 1.2 }}
        >
          ✕
        </button>
      )}

      <span style={{
        fontSize: 10, color: "var(--text-faint)",
        fontFamily: "ui-monospace, monospace",
      }}>
        {tokens.toLocaleString()} tokens
      </span>

      {showCancel && (
        <button onClick={onCancel} style={{
          padding: "2px 10px", fontSize: 11, color: "var(--err)",
        }}>
          取消
        </button>
      )}

      {status === "error" && errorDetail && (
        <span
          title={errorDetail}
          style={{
            fontSize: 11, color: "var(--err)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            maxWidth: 280,
          }}
        >
          ⚠ {errorDetail}
        </span>
      )}
    </div>
  );
}
