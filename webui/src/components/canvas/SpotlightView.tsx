// SpotlightView — one specialist focused on the left (~65%) + 3 minis on the right.
//
// Layout via .canvas-grid--spotlight (grid-template-columns: 1fr 320px).
// The CSS grid transition handles the bento↔spotlight morph natively.
// The right column is fully interactive while streaming continues.

import type { Agent } from "../../types";
import type { Turn } from "../../api/client";
import { LargePanel } from "./LargePanel";
import { SidePanelStack } from "./SidePanelStack";

interface Props {
  specialists: Agent[];
  spotlightAgent: string;
  specialistHistories: Record<string, Turn[]>;
  /** Whether a standalone-chat WS is currently open for the spotlit agent. */
  standaloneActive: boolean;
  onBackToBento: () => void;
  onSwitch: (name: string) => void;
  onToggleStandalone: () => void;
  onCancelStandalone: () => void;
  onClearHistory: () => void;
  onEdit: () => void;
}

export function SpotlightView({
  specialists, spotlightAgent, specialistHistories,
  standaloneActive,
  onBackToBento, onSwitch, onToggleStandalone, onCancelStandalone,
  onClearHistory, onEdit,
}: Props) {
  const agent = specialists.find((a) => a.name === spotlightAgent);
  if (!agent) {
    // Shouldn't happen — fall back to empty
    return null;
  }
  const turns = specialistHistories[spotlightAgent] ?? [];
  return (
    <div className="canvas-grid canvas-grid--spotlight">
      {/* keyed so React rebuilds the panel cleanly on agent switch
          (provides a fresh fadeIn animation per switch) */}
      <LargePanel
        key={spotlightAgent}
        agent={agent}
        turns={turns}
        standaloneActive={standaloneActive}
        onBackToBento={onBackToBento}
        onToggleStandalone={onToggleStandalone}
        onCancelStandalone={onCancelStandalone}
        onClearHistory={onClearHistory}
        onEdit={onEdit}
      />
      <SidePanelStack
        specialists={specialists}
        spotlightAgent={spotlightAgent}
        specialistHistories={specialistHistories}
        onSwitch={onSwitch}
      />
    </div>
  );
}
