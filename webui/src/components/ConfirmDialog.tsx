// Generic confirmation dialog (used for delete-agent).
// Returns the result via onConfirm / onCancel.

import { useEffect } from "react";

interface Props {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title, message,
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger = false,
  onConfirm, onCancel,
}: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onConfirm, onCancel]);

  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed", inset: 0,
        background: "rgba(15, 23, 42, 0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1001,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 380, maxWidth: "92vw",
          background: "var(--bg)",
          borderRadius: 10,
          boxShadow: "0 12px 40px rgba(15, 23, 42, 0.25)",
          padding: 20,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>
          {title}
        </div>
        <div style={{
          fontSize: 12, color: "var(--text-dim)", lineHeight: 1.5,
          marginBottom: 18, whiteSpace: "pre-wrap",
        }}>
          {message}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onCancel}>{cancelLabel}</button>
          <button
            className="primary"
            onClick={onConfirm}
            style={danger ? {
              background: "var(--err)",
              borderColor: "var(--err)",
            } : undefined}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
