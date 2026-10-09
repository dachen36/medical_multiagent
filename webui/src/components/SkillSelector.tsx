// Inline skill editor for the DetailPanel.
//
// Two stacked lists:
//   1. 已添加 (N)        — current skills, each with an ✕ button
//   2. 可添加 (M)        — remaining skills from the registry, click to add
//
// Stateless w.r.t. the network: it just calls `onChange(newSkillList)`.
// The parent is responsible for PUT'ing the change and reloading.
//
// UX choices:
//   - Click on an attached row's ✕ to remove.
//   - Click on an unattached row to add.
//   - Clicking the row body on attached is a no-op (so users don't toggle
//     accidentally); only the ✕ removes.
//   - Sections are collapsible via `defaultExpanded` prop.

import { useState } from "react";
import type { Skill } from "../types";

interface Props {
  attached: string[];
  available: Skill[];
  saving: boolean;            // disables all controls while a save is in flight
  onChange: (newAttached: string[]) => void;
}

export function SkillSelector({ attached, available, saving, onChange }: Props) {
  const attachedSet = new Set(attached);
  const attachedDetails = available
    .filter((s) => attachedSet.has(s.name))
    .sort((a, b) => a.name.localeCompare(b.name));
  const unattached = available
    .filter((s) => !attachedSet.has(s.name))
    .sort((a, b) => a.name.localeCompare(b.name));

  function remove(name: string) {
    if (saving) return;
    onChange(attached.filter((n) => n !== name));
  }
  function add(name: string) {
    if (saving) return;
    onChange([...attached, name]);
  }

  return (
    <section>
      <SectionHeader>技能 ({attachedDetails.length})</SectionHeader>
      {attachedDetails.length === 0 ? (
        <div style={{ fontSize: 11, color: "var(--text-faint)", marginBottom: 8 }}>
          暂未添加技能 · 从下方选择
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
          {attachedDetails.map((s) => (
            <div
              key={s.name}
              style={{
                background: "var(--bg)",
                border: "1px solid var(--border-soft)",
                borderRadius: 6,
                padding: "8px 10px",
                fontSize: 12,
                opacity: saving ? 0.5 : 1,
                transition: "opacity 0.12s",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 600, color: "var(--text)" }}>{s.name}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{
                    fontSize: 10, color: "var(--accent)",
                    padding: "1px 7px", borderRadius: 3,
                    background: "var(--accent-soft)",
                    fontWeight: 600,
                  }}>
                    {s.domain}
                  </span>
                  <button
                    onClick={() => remove(s.name)}
                    disabled={saving}
                    title="从该 agent 移除"
                    style={{
                      padding: "0 6px", fontSize: 11, lineHeight: "18px",
                      color: "var(--err)", border: "1px solid var(--border-soft)",
                    }}
                  >
                    ✕
                  </button>
                </div>
              </div>
              {s.description && (
                <div style={{
                  fontSize: 11, color: "var(--text-dim)",
                  marginTop: 4, lineHeight: 1.4,
                }}>
                  {s.description.length > 120
                    ? s.description.slice(0, 120) + "…"
                    : s.description}
                </div>
              )}
              {s.has_scripts && (
                <div style={{ fontSize: 10, color: "var(--accent)", marginTop: 4, fontWeight: 600 }}>
                  ▸ 含脚本
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {unattached.length > 0 && (
        <>
          <SectionHeader>可添加 ({unattached.length})</SectionHeader>
          <div style={{
            display: "flex", flexDirection: "column", gap: 2,
            maxHeight: 220, overflow: "auto",
            padding: "4px 0",
            border: "1px solid var(--border-soft)",
            borderRadius: 6,
            background: "var(--bg)",
          }}>
            {unattached.map((s) => (
              <button
                key={s.name}
                onClick={() => add(s.name)}
                disabled={saving}
                title="点击添加到该 agent"
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "5px 10px",
                  fontSize: 11,
                  background: "transparent",
                  border: "none",
                  borderRadius: 0,
                  color: "var(--text)",
                  textAlign: "left",
                  cursor: saving ? "not-allowed" : "pointer",
                }}
                onMouseEnter={(e) => {
                  if (!saving) e.currentTarget.style.background = "var(--bg-elev)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
              >
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{
                    color: "var(--accent)", fontWeight: 700, width: 12, textAlign: "center",
                  }}>+</span>
                  <span style={{ fontFamily: "ui-monospace, monospace" }}>{s.name}</span>
                </span>
                <span style={{
                  fontSize: 9, color: "var(--text-faint)",
                  padding: "1px 6px", borderRadius: 3,
                  background: "var(--bg-soft)",
                }}>
                  {s.domain}
                </span>
              </button>
            ))}
          </div>
        </>
      )}

      {saving && (
        <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 6 }}>
          ⏳ 正在保存…
        </div>
      )}
    </section>
  );
}


function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h3 style={{
      fontSize: 11, fontWeight: 700, letterSpacing: 1.2,
      color: "var(--accent)", margin: "0 0 8px 0",
      textTransform: "uppercase",
    }}>
      {children}
    </h3>
  );
}
