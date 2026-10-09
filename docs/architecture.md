# 系统架构

## 1. 整体架构

系统采用**三层分层**设计，4 个 Specialist Agent 共享底层运行时，由 Coordinator Agent 统一调度：

```
                          用户请求
                             │
                             ▼
                    ┌─────────────────┐
                    │ team-coordinator │  (协调调度层)
                    │   7 个协调工具    │
                    └────────┬────────┘
                             │ dispatch
              ┌──────────────┼──────────────┬──────────────┐
              ▼              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
     │  intake    │  │ knowledge  │  │  analysis  │  │ evolution  │
     │ specialist │  │ specialist │  │ specialist │  │ specialist │
     │  (yellow)  │  │  (blue)    │  │   (red)    │  │  (green)   │
     └──────┬─────┘  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
            │               │               │               │
            └───────────────┴───────────────┴───────────────┘
                             │ 共享
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐
  │  Layer 3:   │   │  Layer 2:    │   │  Layer 1:    │
  │  行为合约    │   │  复用能力     │   │  共享运行时   │
  │  (4 skills) │   │  (5 skills)  │   │ clinical-core│
  └─────────────┘   └──────────────┘   └──────────────┘
                                             │
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                         25+ Python     63 教材 .md    KG 84K 实体
                          工具脚本      DuckDB 向量库   药物库 2587 条
```

### 三层说明

| 层级 | 名称 | 内容 | 独立性 |
|------|------|------|--------|
| **Layer 1** | 共享运行时 | `clinical-core` skill（145MB）— 25+ 工具 + 63 教材 + KG + RAG + 药物库 | 所有 specialist 共享 |
| **Layer 2** | 复用能力 | 5 个 `medical-*` skill — 实体抽取、诊断推理、NLP 解析、诊断评估、自我诊断 | 多个 specialist 复用 |
| **Layer 3** | 行为合约 | 4 个 protocol skill — intake/hybrid-search/analysis/evolution | 每个 specialist 专属 |

---

## 2. 多智能体协作模式

### 模式 A：P3.4 并行 Fan-out（快速多面分析）

所有 specialist 同时启动，各自独立执行，结果由协调器汇总。

```
用户请求 → coordinator 同时 dispatch 4 个 specialist
              │                │                │                │
              ▼                ▼                ▼                ▼
          intake          knowledge        analysis        evolution
              │                │                │                │
              └────────────────┴────────────────┴────────────────┘
                               │
                          coordinator 综合 → 最终报告
```

**适用场景**：标准临床问诊、快速多面分析

### 模式 B：P10 Supervisor 协调者（复杂多步）

按临床流程串行派发，coordinator 可观察、指导、修订各 specialist 的行为。

```
用户请求
   │
   ▼
coordinator dispatch(intake) ──→ intake 执行 ──→ coordinator observe
   │
   ▼
coordinator dispatch(knowledge + analysis) ──→ 并行执行 ──→ coordinator observe
   │
   ▼
coordinator dispatch(evolution) ──→ evolution 执行 ──→ coordinator observe
   │
   ▼
coordinator publish_final_report()
```

**适用场景**：复杂多步诊断、需要中途调整策略

### 7 个 Coordinator 工具

| 工具 | 类型 | 用途 |
|------|------|------|
| `dispatch(agent, task, wait_for)` | async | 派发任务到 specialist |
| `observe(agent)` | sync | 查看 specialist 实时状态 |
| `proceed(agent, instructions)` | async | 让已 plan() 的 specialist 继续 |
| `revise(agent, instructions, todos)` | async | 中途替换 specialist 的 todo 列表 |
| `finish_agent(agent, reason)` | sync | 让 specialist 早停 |
| `assert_goal_coverage(criteria)` | sync | 自我确认目标是否达成 |
| `publish_final_report(text)` | sync | 终止运行，发布最终报告 |

---

## 3. 4-Agent 详细设计

### intake-specialist (yellow) — 问诊采集

**对应能力柱**：结构化问诊 + 病历管理

| 维度 | 内容 |
|------|------|
| 职责 | 9 段式问诊、病历 CRUD、OCR 识别、实体抽取、红旗筛查 |
| 挂载 Skill | `clinical-core`, `intake-protocol`, `medical-entity-extractor`, `clinical-nlp-extractor` |
| 核心工具 | `interview_flow.py`, `doctor_memory.py`, `ocr_image.py`, `hybrid_search.py --toc-only` |
| 输出 JSON | `{patient, chief_complaint, interview_sections, entities, ocr_results, red_flag}` |

### knowledge-specialist (blue) — 知识检索

**对应能力柱**：混合搜索 + 知识图谱 + 盲区补充

| 维度 | 内容 |
|------|------|
| 职责 | TOC+RAG+KG 三引擎搜索、视频知识检索、盲区自动发现与补充 |
| 挂载 Skill | `clinical-core`, `hybrid-search-protocol` |
| 核心工具 | `hybrid_search.py`, `kg_query.py`, `knowledge_gap_filler.py` |
| 输出 JSON | `{query, engines_used, toc_results, rag_results, kg_results, blind_spots, summary}` |

### analysis-specialist (red) — 智能分析

**对应能力柱**：药物检查 + 化验解读 + 鉴别诊断

| 维度 | 内容 |
|------|------|
| 职责 | 药物相互作用四档检查、化验五档解读、5 维度鉴别诊断、认知偏差自检 |
| 挂载 Skill | `clinical-core`, `analysis-protocol`, `medical-diagnostic-agent`, `clinical-diagnostic-reasoning`, `diagnostic-evaluation-agent` |
| 核心工具 | `drug_interaction_db.py`, `lab_interpreter.py`, `hybrid_search.py` |
| 输出 JSON | `{drug_interactions, lab_interpretation, differential_diagnosis, bias_check}` |

### evolution-specialist (green) — 自我进化

**对应能力柱**：自我进化 + 记忆管理

| 维度 | 内容 |
|------|------|
| 职责 | 四级递进进化、诊断模式追踪、KG 关系注入、临床规律提炼 |
| 挂载 Skill | `clinical-core`, `evolution-protocol` |
| 核心工具 | `self_evolution.py`, `doctor_memory.py`, `knowledge_gap_filler.py` |
| 输出 JSON | `{evolution_run, current_state, clinical_rules, memory_update}` |

### team-coordinator (purple) — 协调调度

| 维度 | 内容 |
|------|------|
| 职责 | 接收用户请求、派发任务到 specialist、汇总综合报告 |
| 工具 | 7 个 coordinator tools（P10 模式）+ Agent tool（P3.4 回退） |
| 特殊规则 | intake 检出红旗 → 立即 publish 120 建议，终止其他 specialist |

---

## 4. 数据架构

### 知识库（63 本教材）

```
knowledge/
├── 01高等数学.md          ── 基础科学 (v01-v05)
├── 06系统解剖学.md        ── 基础医学 (v06-v15)
├── 19诊断学.md            ── 临床核心 (v19-v30)
├── 31皮肤性病学.md        ── 专科 (v31-v51)
├── 55中医临床学.md        ── 补充 (v55-v64)
└── ... (共 63 本)
```

覆盖：基础科学 → 基础医学 → 临床核心 → 专科 → 中医/药典/药物相互作用

### 向量库（DuckDB）

| 属性 | 值 |
|------|-----|
| 文件 | `rag_knowledge.duckdb` |
| 大小 | 32 MB |
| 知识块数 | 5,075 |
| 用途 | RAG 语义搜索 |

### 知识图谱（KG）

| 属性 | 值 |
|------|-----|
| 文件 | `knowledge_graph.json` (21 MB) + `knowledge_graph_index.json` (19 MB) |
| 实体数 | 84,307 |
| 关系数 | 120,193 |
| 覆盖 | 疾病、症状、药物、检查、科室 |

### 药物库

| 属性 | 值 |
|------|-----|
| 文件 | `drug_interaction_db.json` (819 KB) + `drug_interaction_index.json` (148 KB) |
| 相互作用记录 | 2,587 条 |
| 药物覆盖 | 3,835 种 |
| 别名映射 | 200+ 中英文 |
| 严重度分级 | X（禁忌）/ D（严重）/ C（中等）/ B（轻微） |

### 检验参考库

| 属性 | 值 |
|------|-----|
| 文件 | `data/lab_reference.json` (18 KB) |
| 大类 | 9 大类 |
| 指标数 | 36 项 |
| 组合规则 | 8 条（细菌感染/肝损伤/胆道梗阻/甲亢/甲减等） |
| 紧急标志 | 8 条（肌酐/钾/血糖/血小板危险值） |

### 数据文件汇总

| 文件 | 大小 | 说明 |
|------|------|------|
| `rag_knowledge.duckdb` | 32 MB | RAG 向量库 |
| `knowledge_graph.json` | 21 MB | KG 实体+关系 |
| `knowledge_graph_index.json` | 19 MB | KG 搜索索引 |
| `drug_interaction_db.json` | 819 KB | 药物相互作用 |
| `knowledge/*.md` | ~40 MB | 63 本教材 |
| `data/lab_reference.json` | 18 KB | 检验参考 |
| **clinical-core 总计** | **~145 MB** | |

---

## 5. WebUI 架构

### 后端（FastAPI）

```
webui/server/
├── app.py                 # FastAPI 应用 + WebSocket 端点
├── scenario_runner.py     # 场景执行器（classic / plan-first / coordinator 三种模式）
├── coordinator_tools.py   # 7 个 coordinator 工具 schema + executor
├── agent_tools.py         # Agent 工具实现
├── agents_io.py           # Agent 定义 I/O
├── llm.py                 # LLM 客户端封装
├── team_types.py          # Pydantic 数据模型
└── models.py / skills_io.py
```

**API 端点**：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/agents` | GET | 获取所有 agent 定义 |
| `/api/skills` | GET | 获取所有 skill |
| `/ws/scenario` | WebSocket | 多 agent 场景执行（P3.4 / P10） |
| `/ws/specialist` | WebSocket | 单 agent 对话 |
| `/api/specialists/{name}/history` | GET | 获取单 agent 历史记录 |

### 前端（React 19）

```
webui/src/
├── App.tsx                 # 主应用（Zustand 状态管理）
├── api/client.ts           # WebSocket + REST 客户端
├── components/
│   ├── ScenarioView.tsx    # 多 agent 场景视图
│   ├── AgentEditor.tsx     # Agent 编辑器
│   ├── SystemPanel.tsx     # 系统面板
│   ├── DetailPanel.tsx     # 详情面板
│   ├── InputBar.tsx        # 输入栏
│   ├── SkillSelector.tsx   # Skill 选择器
│   └── ...
└── types.ts
```

---

## 6. 项目目录结构

```
OpenHarness/
├── src/openharness/            # Python 包源码
│   ├── cli.py                  # CLI 入口（Typer）
│   ├── coordinator/            # Agent 定义模型 + 协调器模式
│   ├── swarm/                  # 多智能体（team lifecycle / mailbox / subprocess）
│   ├── skills/                 # Skill 加载器 + 8 个内置 skill
│   ├── tools/                  # 44 个内置工具
│   ├── api/                    # LLM 客户端（Anthropic / OpenAI / Codex / Copilot）
│   ├── config/                 # 配置管理
│   ├── prompts/                # 系统提示词生成
│   └── ...
├── webui/
│   ├── server/                 # FastAPI 后端
│   └── src/                    # React 前端
├── scripts/
│   ├── multi_agent_team.py     # 多智能体演示脚本
│   └── ...
├── tests/                      # pytest 测试
├── docs/                       # 项目文档
├── pyproject.toml              # Python 项目配置
└── README.md                   # 英文 README
```

**运行时数据**（不在 Git 中）：

```
~/.openharness/
├── agents/                     # 5 个 agent 定义 .md
│   ├── intake-specialist.md
│   ├── knowledge-specialist.md
│   ├── analysis-specialist.md
│   ├── evolution-specialist.md
│   └── team-coordinator.md
├── skills/
│   ├── clinical-core/          # 145 MB 共享运行时
│   ├── intake-protocol/        # Layer 3 行为合约
│   ├── hybrid-search-protocol/
│   ├── analysis-protocol/
│   └── evolution-protocol/
├── teams/                      # 运行时团队目录（mailbox）
└── settings.json               # LLM provider 配置
```
