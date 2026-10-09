// Agent color → CSS variable mapping.
//
// Lifted from the old components/AgentCard.tsx so that the new canvas/
// components don't need to import a defunct module just for one helper.

import type { AgentColor } from "../types";

export function colorToVar(c: AgentColor): string {
  return `var(--c-${c})`;
}
