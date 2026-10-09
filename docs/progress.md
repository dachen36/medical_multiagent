# 开发进度

## 里程碑总览

| 阶段 | 状态 | 内容 |
|------|------|------|
| **V1** | ✅ 完成 | 4-Agent 按临床流程（triage/history/diagnostic/care），105MB 数据迁移 |
| **V2** | ✅ 完成 | 4-Agent 按 PPT 能力柱重分（intake/knowledge/analysis/evolution），KG 迁移，145MB |
| **V3** | 🔄 规划中 | 增强 WebUI 交互、真实场景优化、生产部署 |

---

## V2 完成清单

| Step | 内容 | 状态 |
|------|------|------|
| 1 | KG 数据迁移（knowledge_graph.json 21MB + index 19MB） | ✅ |
| 2 | V1 agents 归档到 `.archive/`，V2 agents 创建（4 个 .md） | ✅ |
| 3 | V1 skills 归档，V2 skills 创建（4 个 SKILL.md + nanobot symlinks） | ✅ |
| 4 | team-coordinator.md 更新为 V2 agent 描述 | ✅ |
| 5 | multi_agent_team.py 更新（AGENT_NAMES/SCENARIOS/mocks） | ✅ |
| 6 | clinical-core/SKILL.md 更新（KG/盲区/进化/OCR 工具说明） | ✅ |
| 7 | WebUI 后端重启（0.0.0.0:8000） | ✅ |
| 8 | 端到端验证（mock + API + LAN） | ✅ |

---

## 各模块状态

### Agent 定义 — ✅ 5/5 就绪

| Agent | 颜色 | 文件 | Skill 数 | 状态 |
|-------|------|------|---------|------|
| intake-specialist | yellow | `~/.openharness/agents/` | 4 | ✅ |
| knowledge-specialist | blue | `~/.openharness/agents/` | 2 | ✅ |
| analysis-specialist | red | `~/.openharness/agents/` | 5 | ✅ |
| evolution-specialist | green | `~/.openharness/agents/` | 2 | ✅ |
| team-coordinator | purple | `~/.openharness/agents/` | — | ✅ |

### Skill 系统 — ✅ 15/15 就绪

| 类型 | 数量 | 说明 |
|------|------|------|
| Layer 1 共享运行时 | 1 | `clinical-core`（145MB） |
| Layer 3 行为合约 | 4 | intake-protocol / hybrid-search / analysis / evolution |
| Layer 2 复用能力（symlink） | 10 | medical-* / clinical-* / book-learning 等 |

### 核心工具验证 — ✅ 6/6 通过

| 工具 | 功能 | 验证方式 |
|------|------|---------|
| `hybrid_search.py` | TOC + RAG 联合搜索 | `hybrid_search.py "发热" --top 5` |
| `kg_query.py` | KG 知识图谱查询 | `kg_query.py "胸痛"` |
| `drug_interaction_db.py` | 药物相互作用 | `check "华法林,阿司匹林"` |
| `lab_interpreter.py` | 检验报告解读 | stdin JSON 输入 |
| `doctor_memory.py` | 病历管理 | `list-patients` |
| `interview_flow.py` | 9 段式问诊 | `flow` |

### WebUI — ✅ 可用

| 功能 | 状态 |
|------|------|
| 后端 API (`/api/agents`, `/api/skills`) | ✅ |
| WebSocket 场景执行（P3.4 classic） | ✅ |
| WebSocket 场景执行（P10 coordinator） | ✅ |
| 前端 4 specialist 卡片展示 | ✅ |
| 局域网访问（192.168.60.187:5173） | ✅ |
| Mock 模式测试 | ✅ |
| 真实 LLM 测试（Qwen3.6-27B） | ✅ |

### 测试覆盖

| 测试类型 | 文件 | 状态 |
|---------|------|------|
| WebUI smoke tests (P3.4-P10) | `webui/scripts/smoke_p*.py` | ✅ 全通过 |
| 多智能体演示 (mock) | `scripts/multi_agent_team.py` | ✅ |
| 多智能体演示 (real LLM) | `scripts/multi_agent_team.py --real` | ✅ |
| 项目单元测试 | `tests/` (29 子目录) | ✅ |

---

## 已知限制

1. **RAG 语义搜索子进程路径** — `hybrid_search.py` 的 rag_search 函数中有一个 Windows Python 路径硬编码。TOC 搜索和 KG 查询不受影响，RAG 在 Linux 上可正常运行。
2. **视频分析依赖外网** — `video_pipeline.py` 需要 yt-dlp、whisper 等额外依赖，暂不推荐在 WebUI 流程中使用。
3. **OCR 需要 Tesseract** — `ocr_image.py` 依赖 Tesseract OCR 引擎，需额外安装。
