// SpecialistDock — bottom strip of compact panels in SynthesisView.
//
// Each cell shows enough that the user can quickly compare which
// specialist contributed what to the final report. Clicking any cell
// promotes that agent to spotlight WITHOUT discarding the synthesis
// text (the canvas state machine pivots to spotlight; synthesis is
// preserved in App-level state).

import type { Agent } from "../../types";
import type { Turn } from "../../api/client";
import { CompactPanel } from "./CompactPanel";

interface Props {
  specialists: Agent[];
  specialistHistories: Record<string, Turn[]>;
  onSpotlight: (name: string) => void;
}

export function SpecialistDock({
  specialists, specialistHistories, onSpotlight,
}: Props) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `repeat(${Math.max(1, specialists.length)}, 1fr)`,
      gap: 10,
      height: "100%",
    }}>
      {specialists.map((a) => {
        const turns = specialistHistories[a.name] ?? [];
        const latest = turns.length > 0 ? turns[turns.length - 1] : null;
        return (
          <CompactPanel
            key={a.name}
            agent={a}
            turn={latest}
            onClick={() => onSpotlight(a.name)}
          />
        );
      })}
    </div>
  );
}
