// 整改方案 S5-F.1 — 知识库 Tab 实装
//
// 5 个子 tab：教材 / 章节 / 知识图谱 / 药物互作 / 病历
// 数据来源：5 个 /api/knowledge/* endpoint
//
// 交互：
//   - 列表 → 点击展开看明细
//   - 子 tab 切换加载数据
//   - 「外链」图标 → 后续 S5-F.2 接知识库聚焦（高亮某个实体/章节）
//   - 「搜索」按书名/章节名/实体名/药名过滤

import { useEffect, useState } from "react";
import { Markdown } from "./Markdown";

type SubTab = "books" | "chapters" | "kg" | "drugs" | "cases";

interface Props {
  /** S5-F.2 — 知识库面板聚焦目标（来自 specialist timeline 的超链接） */
  focusTarget?: { type: SubTab; id: string } | null;
  /** S5-F.2 — 跳到知识库后，告知 App 已完成 */
  onFocused?: () => void;
}

const SUB_TABS: { id: SubTab; label: string; icon: string }[] = [
  { id: "books",   label: "教材",   icon: "📘" },
  { id: "chapters",label: "章节",   icon: "📑" },
  { id: "kg",      label: "知识图谱", icon: "🕸️" },
  { id: "drugs",   label: "药物互作", icon: "💊" },
  { id: "cases",   label: "病历",   icon: "📋" },
];


export function KnowledgeBase({ focusTarget, onFocused }: Props) {
  const [subTab, setSubTab] = useState<SubTab>("books");

  // focusTarget 变化时切到对应子 tab
  useEffect(() => {
    if (focusTarget?.type) {
      setSubTab(focusTarget.type);
    }
  }, [focusTarget]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* 子 tab bar */}
      <div style={{
        display: "flex", gap: 0, padding: "0 24px",
        borderBottom: "1px solid var(--border-soft)",
        background: "var(--bg-soft)", flexShrink: 0,
      }}>
        {SUB_TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            style={{
              padding: "9px 14px", fontSize: 12,
              fontWeight: subTab === t.id ? 600 : 400,
              color: subTab === t.id ? "var(--accent)" : "var(--text-dim)",
              background: "transparent",
              border: "none",
              borderBottom: subTab === t.id
                ? "2px solid var(--accent)" : "2px solid transparent",
              borderRadius: 0, cursor: "pointer",
              marginBottom: -1,
            }}
          >
            {t.icon} {t.label}
          </button>
        ))}
        {focusTarget && (
          <span style={{
            marginLeft: "auto", fontSize: 10, color: "var(--accent-dim)",
            alignSelf: "center",
          }}>
            🎯 已聚焦到 {focusTarget.type}/{focusTarget.id}
          </span>
        )}
      </div>

      {/* 子 tab 内容 */}
      <div style={{ flex: 1, overflow: "auto", padding: "16px 24px" }}>
        {subTab === "books"   && <BooksPane focusId={focusTarget?.id} />}
        {subTab === "chapters"&& <ChaptersPane focusId={focusTarget?.id} />}
        {subTab === "kg"      && <KGPane />}
        {subTab === "drugs"   && <DrugsPane focusId={focusTarget?.id} />}
        {subTab === "cases"   && <CasesPane focusId={focusTarget?.id} />}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// 教材子 tab
// ---------------------------------------------------------------------------
function BooksPane({ focusId }: { focusId?: string }) {
  const [books, setBooks] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/knowledge/books${query ? `?q=${encodeURIComponent(query)}` : ""}`)
      .then((r) => r.json()).then((d) => {
        if (cancelled) return;
        setBooks(d.books || []);
        if (focusId) setExpanded(focusId);
      });
    return () => { cancelled = true; };
  }, [query, focusId]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <input
          type="text" value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索教材（书名 / 出版社）…"
          style={{ flex: 1, maxWidth: 320, padding: "6px 10px", fontSize: 12 }}
        />
        <span style={{ fontSize: 11, color: "var(--text-faint)" }}>共 {books.length} 本</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
        {books.slice(0, 24).map((b) => {
          const isOpen = expanded === b.id;
          return (
            <div key={b.id} style={{
              border: `1px solid ${focusId === b.id ? "var(--accent)" : "var(--border-soft)"}`,
              borderRadius: 6, background: "var(--bg)", padding: "10px 12px",
            }}>
              <div
                onClick={() => setExpanded(isOpen ? null : b.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 8, cursor: "pointer",
                }}
              >
                <span style={{ fontSize: 16 }}>📘</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: "var(--text-faint)" }}>
                    {b.publisher} · {b.edition} · {b.year} · {b.chapters} 章
                  </div>
                </div>
                <span style={{ fontSize: 10, color: "var(--text-faint)" }}>{isOpen ? "▲" : "▼"}</span>
              </div>
              {isOpen && (
                <div style={{
                  marginTop: 8, padding: 8,
                  background: "var(--bg-soft)", borderRadius: 4,
                  fontSize: 11, color: "var(--text-dim)", lineHeight: 1.6,
                }}>
                  <div><b>教材 ID：</b>{b.id}</div>
                  <div><b>版次：</b>{b.edition}（{b.year}）</div>
                  <div><b>章节数：</b>{b.chapters}</div>
                  <div style={{ marginTop: 4, color: "var(--text-faint)" }}>
                    点击进入「章节」子 tab 查看 {b.name} 的完整目录
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {books.length > 24 && (
        <div style={{ marginTop: 12, textAlign: "center", color: "var(--text-faint)", fontSize: 11 }}>
          显示前 24 本 · 共 {books.length} 本 · 搜索缩小范围
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// 章节子 tab
// ---------------------------------------------------------------------------
function ChaptersPane({ focusId }: { focusId?: string }) {
  const [chapters, setChapters] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [bookId, setBookId] = useState<string>("");
  const [book, setBook] = useState<any>(null);

  useEffect(() => {
    let cancelled = false;
    const url = bookId
      ? `/api/knowledge/chapters?book=${encodeURIComponent(bookId)}&limit=50`
      : `/api/knowledge/chapters?limit=20`;
    fetch(url).then((r) => r.json()).then((d) => {
      if (cancelled) return;
      setChapters(d.chapters || []);
      setBook(d.book || null);
      if (focusId) setExpanded(focusId);
    });
    return () => { cancelled = true; };
  }, [bookId, focusId]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <label style={{ fontSize: 12, color: "var(--text-dim)" }}>选教材：</label>
        <select
          value={bookId}
          onChange={(e) => setBookId(e.target.value)}
          style={{ padding: "4px 8px", fontSize: 12, minWidth: 200 }}
        >
          <option value="">（全部 5 本代表）</option>
          <option value="01-neike">内科学</option>
          <option value="03-erke">儿科学</option>
          <option value="07-zhenduan">诊断学</option>
          <option value="11-huxi">呼吸病学</option>
          <option value="13-shennaio">肾脏内科学</option>
        </select>
        {book && (
          <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
            {book.name} · {book.chapters} 章
          </span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-faint)" }}>
          共 {chapters.length} 章
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 4 }}>
        {chapters.map((c) => {
          const isOpen = expanded === c.id;
          return (
            <div key={c.id} style={{
              border: `1px solid ${focusId === c.id ? "var(--accent)" : "var(--border-soft)"}`,
              borderRadius: 4, background: "var(--bg)", padding: "8px 12px",
            }}>
              <div onClick={() => setExpanded(isOpen ? null : c.id)}
                style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                <span style={{ fontSize: 11, color: "var(--text-faint)", minWidth: 50 }}>{c.number}</span>
                <span style={{ flex: 1, fontSize: 12, fontWeight: 500, color: "var(--text)" }}>{c.title}</span>
                <span style={{ fontSize: 10, color: "var(--text-faint)" }}>
                  {c.subsections} 节 · {c.key_concepts} 关键概念
                </span>
                <span style={{ fontSize: 10, color: "var(--text-faint)" }}>{isOpen ? "▲" : "▼"}</span>
              </div>
              {isOpen && (
                <div style={{
                  marginTop: 6, padding: 8,
                  background: "var(--bg-soft)", borderRadius: 3,
                  fontSize: 11, color: "var(--text-dim)", lineHeight: 1.6,
                }}>
                  <div><b>章节 ID：</b>{c.id}</div>
                  <div><b>所属教材：</b>{c.book}</div>
                  <div style={{ marginTop: 4, color: "var(--text-faint)" }}>
                    知识智能体可在 TOC 索引中搜索到本章节并引用
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// 知识图谱子 tab
// ---------------------------------------------------------------------------
function KGPane() {
  const [entities, setEntities] = useState<any[]>([]);
  const [relations, setRelations] = useState<any[]>([]);
  const [type, setType] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    const entUrl = type ? `/api/knowledge/entities?type=${type}&limit=30` : `/api/knowledge/entities?limit=30`;
    fetch(entUrl).then((r) => r.json()).then((d) => {
      if (cancelled) return;
      setEntities(d.entities || []);
    });
    fetch("/api/knowledge/relations?limit=20").then((r) => r.json()).then((d) => {
      if (cancelled) return;
      setRelations(d.relations || []);
    });
    return () => { cancelled = true; };
  }, [type]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <label style={{ fontSize: 12, color: "var(--text-dim)" }}>类型：</label>
        <select value={type} onChange={(e) => setType(e.target.value)}
          style={{ padding: "4px 8px", fontSize: 12 }}>
          <option value="">全部</option>
          <option value="disease">疾病</option>
          <option value="symptom">症状</option>
          <option value="drug">药物</option>
          <option value="test">检查</option>
        </select>
        <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
          {entities.length} 实体 · 84,307 总 · 120,193 关系
        </span>
      </div>

      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12,
      }}>
        {/* 实体列表 */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
            实体（示例 {entities.length} 个）
          </div>
          <div style={{ display: "grid", gap: 4 }}>
            {entities.map((e) => (
              <div key={e.id} style={{
                padding: "6px 10px",
                border: "1px solid var(--border-soft)",
                borderRadius: 4, background: "var(--bg)",
                display: "flex", alignItems: "center", gap: 8,
              }}>
                <span style={{ fontSize: 13 }}>
                  {e.type === "disease" ? "🏥" : e.type === "symptom" ? "🤒" :
                   e.type === "drug" ? "💊" : "🔬"}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text)" }}>{e.name}</div>
                  {e.aliases?.length > 0 && (
                    <div style={{ fontSize: 10, color: "var(--text-faint)" }}>
                      别名：{e.aliases.join("、")}
                    </div>
                  )}
                </div>
                <span style={{ fontSize: 10, color: "var(--text-faint)" }}>
                  {e.kg_relations} 关系
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* 关系列表 */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
            关系（示例 {relations.length} 条）
          </div>
          <div style={{ display: "grid", gap: 4 }}>
            {relations.map((r, idx) => (
              <div key={idx} style={{
                padding: "6px 10px",
                border: "1px solid var(--border-soft)",
                borderRadius: 4, background: "var(--bg)",
                fontSize: 11, lineHeight: 1.5,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ fontFamily: "ui-monospace, monospace", color: "var(--accent-dim)" }}>{r.from.replace("kg-", "")}</span>
                  <span style={{ color: "var(--text-faint)" }}>→</span>
                  <span style={{ fontWeight: 600, color: "var(--text)" }}>{r.rel}</span>
                  <span style={{ color: "var(--text-faint)" }}>→</span>
                  <span style={{ fontFamily: "ui-monospace, monospace", color: "var(--accent-dim)" }}>{r.to.replace("kg-", "")}</span>
                </div>
                <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 2 }}>
                  权重 {r.weight} · 证据 {r.evidence_count} 例
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// 药物互作子 tab
// ---------------------------------------------------------------------------
function DrugsPane({ focusId }: { focusId?: string }) {
  const [items, setItems] = useState<any[]>([]);
  const [severity, setSeverity] = useState<string>("");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const url = severity
      ? `/api/knowledge/drug-interactions?severity=${severity}&limit=50`
      : `/api/knowledge/drug-interactions?limit=50`;
    fetch(url).then((r) => r.json()).then((d) => {
      if (cancelled) return;
      setItems(d.interactions || []);
      if (focusId) setExpanded(focusId);
    });
    return () => { cancelled = true; };
  }, [severity, focusId]);

  const SEV_COLORS: Record<string, string> = {
    X: "#dc2626", D: "#ea580c", C: "#ca8a04", B: "#64748b",
  };
  const SEV_LABELS: Record<string, string> = {
    X: "禁忌", D: "严重", C: "中等", B: "轻微",
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
        <label style={{ fontSize: 12, color: "var(--text-dim)" }}>严重程度：</label>
        {["", "X", "D", "C", "B"].map((s) => (
          <button
            key={s || "all"}
            onClick={() => setSeverity(s)}
            style={{
              padding: "3px 10px", fontSize: 11,
              border: "1px solid " + (severity === s ? SEV_COLORS[s] || "var(--accent)" : "var(--border)"),
              background: severity === s ? (SEV_COLORS[s] || "var(--accent-soft)") : "var(--bg)",
              color: severity === s ? "#fff" : "var(--text-dim)",
              borderRadius: 3, cursor: "pointer",
              fontWeight: severity === s ? 600 : 400,
            }}
          >
            {s || "全部"}
          </button>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-faint)" }}>
          {items.length} 条 / 共 2,587 条
        </span>
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        {items.map((d) => {
          const isOpen = expanded === d.id;
          return (
            <div key={d.id} style={{
              border: `1px solid ${focusId === d.id ? "var(--accent)" : "var(--border-soft)"}`,
              borderLeft: `3px solid ${SEV_COLORS[d.severity] || "var(--text-faint)"}`,
              borderRadius: 4, background: "var(--bg)",
            }}>
              <div onClick={() => setExpanded(isOpen ? null : d.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 12px", cursor: "pointer",
                }}>
                <span style={{
                  padding: "1px 8px", borderRadius: 3,
                  background: SEV_COLORS[d.severity], color: "#fff",
                  fontSize: 10, fontWeight: 700, minWidth: 18, textAlign: "center",
                }}>{d.severity}</span>
                <span style={{
                  fontSize: 13, fontWeight: 600, color: "var(--text)",
                }}>
                  {d.drug_a} <span style={{ color: "var(--text-faint)" }}>+</span> {d.drug_b}
                </span>
                <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
                  {SEV_LABELS[d.severity] || ""}
                </span>
                <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text-faint)" }}>
                  {isOpen ? "▲" : "▼"}
                </span>
              </div>
              {isOpen && (
                <div style={{
                  padding: "8px 12px 12px",
                  borderTop: "1px solid var(--border-soft)",
                  fontSize: 12, color: "var(--text-dim)", lineHeight: 1.7,
                }}>
                  <div><b>机制：</b>{d.mechanism}</div>
                  <div><b>管理建议：</b>{d.management}</div>
                  <div style={{ marginTop: 4, fontSize: 10, color: "var(--text-faint)" }}>
                    ID: {d.id}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// 病历子 tab
// ---------------------------------------------------------------------------
function CasesPane({ focusId }: { focusId?: string }) {
  const [cases, setCases] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/knowledge/cases?limit=20").then((r) => r.json()).then((d) => {
      if (cancelled) return;
      setCases(d.cases || []);
      if (focusId) setExpanded(focusId);
    });
    return () => { cancelled = true; };
  }, [focusId]);

  const STATUS_COLORS: Record<string, string> = {
    active: "var(--ok)", follow_up: "var(--accent)", resolved: "var(--text-faint)",
  };
  const STATUS_LABELS: Record<string, string> = {
    active: "在诊", follow_up: "随访", resolved: "已愈",
  };

  return (
    <div>
      <div style={{ marginBottom: 10, fontSize: 11, color: "var(--text-faint)" }}>
        共 {cases.length} 例 / 总 20 例 / 175 条就诊
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {cases.map((c) => {
          const isOpen = expanded === c.id;
          return (
            <div key={c.id} style={{
              border: `1px solid ${focusId === c.id ? "var(--accent)" : "var(--border-soft)"}`,
              borderRadius: 4, background: "var(--bg)",
            }}>
              <div onClick={() => setExpanded(isOpen ? null : c.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 12px", cursor: "pointer",
                }}>
                <span style={{ fontSize: 13 }}>📋</span>
                <span style={{
                  fontSize: 12, fontWeight: 600, color: "var(--text)",
                  minWidth: 140,
                }}>{c.id}</span>
                <span style={{ fontSize: 12, color: "var(--text)" }}>
                  {c.name} · {c.age} 岁 · {c.gender}
                </span>
                <span style={{ fontSize: 11, color: "var(--text-dim)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  「{c.chief_complaint}」→ {c.diagnosis}
                </span>
                <span style={{
                  fontSize: 10, padding: "1px 6px", borderRadius: 3,
                  background: STATUS_COLORS[c.status] || "var(--bg-elev)",
                  color: "#fff", fontWeight: 600,
                }}>{STATUS_LABELS[c.status] || c.status}</span>
                <span style={{ fontSize: 10, color: "var(--text-faint)" }}>{isOpen ? "▲" : "▼"}</span>
              </div>
              {isOpen && (
                <div style={{
                  padding: "8px 12px 12px",
                  borderTop: "1px solid var(--border-soft)",
                  fontSize: 12, color: "var(--text-dim)", lineHeight: 1.7,
                }}>
                  <div><b>主诉：</b>{c.chief_complaint}</div>
                  <div><b>诊断：</b>{c.diagnosis}</div>
                  <div style={{ marginTop: 6 }}>
                    <b>进化记录：</b>
                    {c.evolution?.patterns_hit || 0} 模式命中 ·
                    {c.evolution?.rules_learned || 0} 规律学到 ·
                    {c.evolution?.kg_injected || 0} KG 注入
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// 辅助函数：被 App.tsx 用
// ---------------------------------------------------------------------------
export function isKnowledgeFocusable(tab: string): boolean {
  return ["books", "chapters", "drugs", "cases"].includes(tab);
}
