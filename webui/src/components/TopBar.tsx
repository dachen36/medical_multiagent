// Top bar with branding and active profile / model display.

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Health } from "../types";

export function TopBar() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <header style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "10px 20px",
      borderBottom: "1px solid var(--border)",
      background: "var(--bg)",
      flexShrink: 0,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{
          display: "inline-block",
          width: 22, height: 22, borderRadius: 5,
          background: "linear-gradient(135deg, var(--accent) 0%, #60a5fa 100%)",
          boxShadow: "0 0 12px var(--accent-glow)",
        }} />
        <span style={{
          fontSize: 15,
          fontWeight: 700,
          color: "var(--text)",
          letterSpacing: 0.3,
        }}>
          MetaClaw
        </span>
        <span style={{ color: "var(--text-faint)", fontSize: 12 }}>
          控制台
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 12 }}>
        {health ? (
          <>
            <span>
              <span style={{ color: "var(--text-faint)" }}>配置: </span>
              <span style={{ color: "var(--accent)", fontWeight: 600 }}>openrouter</span>
            </span>
            <span>
              <span style={{ color: "var(--text-faint)" }}>模型: </span>
              <span style={{ color: "var(--text)" }}>Qwen3.6-27B</span>
            </span>
            <span style={{
              display: "flex", alignItems: "center", gap: 6,
              color: "var(--ok)", fontWeight: 600,
            }}>
              <span style={{
                width: 7, height: 7, borderRadius: "50%",
                background: "var(--ok)",
                boxShadow: "0 0 8px var(--ok)",
              }} />
              已连接
            </span>
          </>
        ) : (
          <span style={{ color: "var(--err)" }}>○ 后端离线</span>
        )}
      </div>
    </header>
  );
}
