// SynthesisView — composite layout for the synthesizing/done phase.
//
// Top region (~1fr): SynthesisPanel streaming the final report.
// Bottom region (~100px): SpecialistDock with 4 compact source tiles —
//   click any to drill back into spotlight for that agent. The streamed
//   text on each dock tile keeps updating live; coordinator events still
//   land in `specialistHistories`.

import type { Agent } from "../../types";
import type { Turn } from "../../api/client";
import { SpecialistDock } from "./SpecialistDock";
import { SynthesisPanel } from "./SynthesisPanel";

type Status = "idle" | "planning" | "running" | "synthesizing" | "done" | "error";

interface Props {
  specialists: Agent[];
  specialistHistories: Record<string, Turn[]>;
  status: Status;
  synthesisText: string;
  errorDetail?: string | null;
  isBusy: boolean;
  onSpotlightSpecialist: (name: string) => void;
  onBackToBento: () => void;
}

export function SynthesisView({
  specialists, specialistHistories,
  status, synthesisText, errorDetail, isBusy,
  onSpotlightSpecialist, onBackToBento,
}: Props) {
  return (
    <div className="canvas-grid canvas-grid--synthesis">
      <SynthesisPanel
        status={status}
        text={synthesisText}
        errorDetail={errorDetail}
        isBusy={isBusy}
        onBackToBento={onBackToBento}
      />
      <SpecialistDock
        specialists={specialists}
        specialistHistories={specialistHistories}
        onSpotlight={onSpotlightSpecialist}
      />
    </div>
  );
}
