// BentoGrid — 2×2 layout of all 4 specialists working in parallel.
//
// The user lands here right after onSend. Each cell streams its own
// thinking and assistant text concurrently; clicking any cell promotes
// it to SpotlightView. Grid layout is driven by .canvas-grid--bento in
// index.css so the transition to spotlight is purely CSS (no JS measure).

import type { Agent } from "../../types";
import type { Turn } from "../../api/client";
import { MediumPanel } from "./MediumPanel";

interface Props {
  specialists: Agent[];
  specialistHistories: Record<string, Turn[]>;
  /** Coordinator mode: agents already dispatched by the supervisor.
   *  Specialists not in this set are dimmed with "等待派发" placeholder. */
  dispatchedAgents?: Set<string>;
  /** When set, ONLY this set of names are considered "active" — used for
   *  coordinator mode to dim non-dispatched panels. Empty/undefined means
   *  treat all as active. */
  coordinatorMode?: boolean;
  onSpotlight: (name: string) => void;
  onEdit: (name: string) => void;
}

export function BentoGrid({
  specialists, specialistHistories,
  dispatchedAgents, coordinatorMode,
  onSpotlight, onEdit,
}: Props) {
  return (
    <div className="canvas-grid canvas-grid--bento view-mount">
      {specialists.map((a) => {
        const turns = specialistHistories[a.name] ?? [];
        const latest = turns.length > 0 ? turns[turns.length - 1] : null;
        // In coordinator mode, dim cells that haven't been dispatched yet
        // (but only AFTER at least one has been dispatched, so the user
        // doesn't see all 4 dimmed during the brief startup window).
        const dimmed = coordinatorMode
          && (dispatchedAgents?.size ?? 0) > 0
          && !dispatchedAgents?.has(a.name);
        return (
          <MediumPanel
            key={a.name}
            agent={a}
            turn={latest}
            dimmed={dimmed}
            onSpotlight={() => onSpotlight(a.name)}
            onEdit={() => onEdit(a.name)}
          />
        );
      })}
    </div>
  );
}
