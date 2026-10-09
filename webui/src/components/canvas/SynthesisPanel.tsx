// SynthesisPanel — top region of SynthesisView, where the final report streams in.
//
// In classic mode this renders the synthesis.token stream; in coordinator
// mode it renders the coordinator's published final report stream (App.tsx
// routes both into `synthesisText`).
//
// Includes an inline error banner if synthesis.error / coordinator.error
// fires while the panel is open (mirror of FinalPane's previous behavior).

import { useEffect, useRef } from "react";
import { Markdown } from "../Markdown";

type Status = "idle" | "planning" | "running" | "synthesizing" | "done" | "error";

interface Props {
  status: Status;
  text: string;
  errorDetail?: string | null;
  isBusy: boolean;
  /** Show a "← 返回总览" affordance so the user can expand the bottom dock
   *  back into a full bento grid. */
  onBackToBento?: () => void;
}

export function SynthesisPanel({
  status, text, errorDetail, isBusy, onBackToBento,
}: Props) {
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [text, status]);

  return (
    <div
      className="view-mount"
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        overflow: "hidden",
      }}
    >
      <div style={{
        padding: "10px 18px",
        borderBottom: "1px solid var(--border-soft)",
        display: "flex", alignItems: "center", gap: 10,
        background: "var(--bg-soft)",
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 16, color: "var(--accent)" }}>📋</span>
        <span style={{ fontWeight: 600, fontSize: 13, color: "var(--text)" }}>
          综合报告
        </span>
        {isBusy && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "2px 8px", borderRadius: 10,
            background: "var(--accent-soft)", color: "var(--accent-dim)",
            fontSize: 10, fontWeight: 600,
          }}>
            <span style={{
              width: 5, height: 5, borderRadius: "50%",
              background: "var(--accent-dim)",
              animation: "pulse 0.9s ease-in-out infinite",
            }} />
            汇总中
          </span>
        )}
        {status === "done" && (
          <span style={{
            padding: "2px 8px", borderRadius: 10,
            background: "#dcfce7", color: "#15803d",
            fontSize: 10, fontWeight: 600,
          }}>
            完成
          </span>
        )}
        <span style={{
          marginLeft: "auto",
          fontSize: 10, color: "var(--text-faint)",
          fontFamily: "ui-monospace, monospace",
        }}>
          {text.length} 字
        </span>
        {onBackToBento && (
          <button
            onClick={onBackToBento}
            title="返回总览（展开 4 个智能体面板）"
            style={{ padding: "1px 10px", fontSize: 11, lineHeight: 1.2 }}
          >
            ⛶ 展开总览
          </button>
        )}
      </div>

      <div
        ref={bodyRef}
        className="panel-content--mount"
        style={{
          flex: 1, overflow: "auto",
          padding: "16px 24px",
          fontSize: 13, lineHeight: 1.7,
          color: "var(--text)",
        }}
      >
        {text ? (
          <Markdown text={text} className="md-body" />
        ) : (
          isBusy
            ? <span style={{ color: "var(--text-faint)" }}>正在等待协调者汇总…</span>
            : null
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
      </div>
    </div>
  );
}
