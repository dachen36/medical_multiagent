// 整改方案 §A6 — 团队管理 Tab
//
// 替代原右侧 DetailPanel 的"agent 编辑/删除入口"。把 4 个 specialist +
// 协调者的完整 CRUD 集中到中部 Tab 内。
//
// S1 阶段：基础 CRUD（编辑/删除/新建） + 列表展示
// S2 阶段：可在此页直接发起"独立咨询" + 历史清空
// S4 阶段：可绑定 skill 库、查看 skill 引用计数

import { useState } from "react";
import type { Agent } from "../types";
import { displayName } from "../types";
import { AgentIcon } from "./AgentIcon";
import { colorToVar } from "./AgentCard";

interface Props {
  specialists: Agent[];          // 已过滤 role !== "coordinator" 的列表
  selectedAgentName?: string | null;
  onSelectAgent?: (name: string) => void;
  onEditAgent?: (name: string) => void;
  onAddAgent?: () => void;
}

export function TeamPane({
  specialists, selectedAgentName, onSelectAgent, onEditAgent, onAddAgent,
}: Props) {
  const [query, setQuery] = useState("");

  const filtered = specialists.filter((a) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return a.name.toLowerCase().includes(q) ||
           (a.display_name ?? "").toLowerCase().includes(q) ||
           a.description.toLowerCase().includes(q);
  });

  return (
    <div style={{
      flex: 1, overflow: "auto", padding: "20px 28px",
    }}>
      <div style={{
        display: "flex", alignItems: "baseline", justifyContent: "space-between",
        marginBottom: 14,
      }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text)" }}>
            团队管理
          </div>
          <div style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 2 }}>
            {specialists.length} 位领域智能体 · 点击编辑/删除/发起独立咨询
          </div>
        </div>
        {onAddAgent && (
          <button
            onClick={onAddAgent}
            className="primary"
            style={{ padding: "6px 14px" }}
          >
            + 添加新智能体
          </button>
        )}
      </div>

      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        marginBottom: 12,
      }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索智能体（名称 / 描述）…"
          style={{
            flex: 1, maxWidth: 320,
            padding: "6px 10px", fontSize: 12,
          }}
        />
        {query && (
          <button onClick={() => setQuery("")} style={{ padding: "4px 10px", fontSize: 11 }}>
            清除
          </button>
        )}
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(2, 1fr)",
        gap: 12,
      }}>
        {filtered.map((a) => (
          <AgentRow
            key={a.name}
            agent={a}
            isSelected={a.name === selectedAgentName}
            onSelect={onSelectAgent ? () => onSelectAgent(a.name) : undefined}
            onEdit={onEditAgent ? () => onEditAgent(a.name) : undefined}
          />
        ))}
      </div>

      {filtered.length === 0 && (
        <div style={{
          padding: "32px 16px", textAlign: "center",
          color: "var(--text-faint)", fontSize: 12,
        }}>
          {query ? `没有匹配 "${query}" 的智能体` : "暂无领域智能体"}
        </div>
      )}
    </div>
  );
}

function AgentRow({
  agent, isSelected, onSelect, onEdit,
}: {
  agent: Agent;
  isSelected: boolean;
  onSelect?: () => void;
  onEdit?: () => void;
}) {
  const color = colorToVar(agent.color);
  return (
    <div style={{
      border: `1px solid ${isSelected ? color : "var(--border)"}`,
      borderRadius: 10,
      background: isSelected ? "var(--accent-soft)" : "var(--bg)",
      padding: "12px 14px",
      display: "flex", gap: 12, alignItems: "center",
      position: "relative", overflow: "hidden",
    }}>
      <span style={{
        position: "absolute",
        top: 0, left: 0, bottom: 0,
        width: 3, background: color,
      }} />
      <div style={{ color, flexShrink: 0, paddingLeft: 4 }}>
        <AgentIcon name={agent.name} size={28} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontWeight: 600, fontSize: 13,
          color: "var(--text)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }} title={agent.name}>
          {displayName(agent)}
        </div>
        <div style={{
          fontSize: 11, color: "var(--text-faint)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          marginTop: 2,
        }} title={agent.description}>
          {agent.description || "—"}
        </div>
        <div style={{
          fontSize: 10, color: "var(--text-faint)",
          marginTop: 4, display: "flex", gap: 6,
        }}>
          <span style={{ color }}>{agent.skills.length} 技能</span>
          <span>·</span>
          <span>{agent.tools.length} 工具</span>
          <span>·</span>
          <span>≤{agent.max_turns} 轮</span>
        </div>
      </div>
      <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
        {onSelect && (
          <button
            onClick={onSelect}
            title="查看时间线"
            style={{ padding: "2px 8px", fontSize: 11 }}
          >
            时间线
          </button>
        )}
        {onEdit && (
          <button
            onClick={onEdit}
            title="编辑"
            style={{ padding: "2px 8px", fontSize: 11 }}
          >
            ✎
          </button>
        )}
      </div>
    </div>
  );
}
