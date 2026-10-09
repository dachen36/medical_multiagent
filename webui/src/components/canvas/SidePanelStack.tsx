// SidePanelStack — the right column of SpotlightView.
//
// 3 CompactPanels stacked vertically, each 1/3 of the column height.
// Excludes the currently spotlit agent (its content is shown large on
// the left). Clicking any mini panel switches the spotlight to that
// agent; the previously-spotlit one slides back into the stack.

import type { Agent } from "../../types";
import type { Turn } from "../../api/client";
import { CompactPanel } from "./CompactPanel";

interface Props {
  specialists: Agent[];
  /** The agent currently showing in the LargePanel — excluded from this stack. */
  spotlightAgent: string;
  specialistHistories: Record<string, Turn[]>;
  onSwitch: (name: string) => void;
}

export function SidePanelStack({
  specialists, spotlightAgent, specialistHistories, onSwitch,
}: Props) {
  const others = specialists.filter((a) => a.name !== spotlightAgent);
  return (
    <div style={{
      display: "grid",
      gridTemplateRows: `repeat(${Math.max(1, others.length)}, 1fr)`,
      gap: 12,
      height: "100%",
    }}>
      {others.map((a) => {
        const turns = specialistHistories[a.name] ?? [];
        const latest = turns.length > 0 ? turns[turns.length - 1] : null;
        return (
          <CompactPanel
            key={a.name}
            agent={a}
            turn={latest}
            onClick={() => onSwitch(a.name)}
          />
        );
      })}
    </div>
  );
}
