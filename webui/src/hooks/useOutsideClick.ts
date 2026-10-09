// useOutsideClick — fires a callback when a `mousedown` happens outside
// the given ref's element.
//
// Why mousedown (not click)?
//   - click fires *after* mouseup, which can be on a different target if
//     the user dragged. mousedown captures the intent at the press point.
//   - Using mousedown also matches the modal-backdrop dismiss pattern used
//     elsewhere in this app (ConfirmDialog, AgentEditor).
//
// The hook is a no-op when `enabled` is false — caller controls when the
// listener is live. Cleanup runs on unmount or when deps change.

import { useEffect, type RefObject } from "react";

export function useOutsideClick(
  ref: RefObject<HTMLElement | null>,
  onOutside: (e: MouseEvent) => void,
  enabled: boolean = true,
) {
  useEffect(() => {
    if (!enabled) return;
    function handler(e: MouseEvent) {
      const el = ref.current;
      if (!el) return;
      if (el.contains(e.target as Node)) return;
      onOutside(e);
    }
    // Capture phase = true so we run before any inner click handlers that
    // might call stopPropagation. The default bubble phase is fine in
    // practice but capture is safer for "I always want to know" semantics.
    document.addEventListener("mousedown", handler, true);
    return () => document.removeEventListener("mousedown", handler, true);
  }, [ref, onOutside, enabled]);
}
