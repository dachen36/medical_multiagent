# 医疗智能体系统 — 基于 OpenHarness 的临床诊断多智能体平台

<p align="center">
  <a href="README.md"><strong>English</strong></a> ·
  <a href="README.zh-CN.md"><strong>简体中文</strong></a>
</p>

4 个临床专家 Agent 协同完成智能诊断。基于 [OpenHarness](https://github.com/HKUDS/OpenHarness) 开源智能体框架构建。

---

## 核心数据规模

| 指标 | 数量 |
|------|------|
| 医学教材 | 63 本（涵盖基础/临床/专科） |
| 知识图谱实体 | 84,307 个 |
| 知识图谱关系 | 120,193 条 |
| 药物相互作用 | 2,587 条 / 3,835 种药物 |
| RAG 向量知识块 | 5,075 个 |
| 检验参考指标 | 36 项 / 9 大类 |
| Python 工具 | 25 个 |

---

## 6 大核心能力

| # | 能力 | 说明 |
|---|------|------|
| 1 | **结构化问诊** | 9 段式临床问诊（主诉→现病史→既往史→过敏→家族史…），自动建病历 |
| 2 | **三引擎混合搜索** | TOC 目录搜索 + RAG 语义搜索 + KG 知识图谱查询，三引擎互补 |
| 3 | **药物安全检查** | 2,587 条相互作用记录，四档分级（X 禁忌 / D 严重 / C 中等 / B 轻微） |
| 4 | **化验报告解读** | 36 项指标 / 8 组合规则 / 8 紧急标志 / 5 档判断（正常→紧急） |
| 5 | **自我进化** | 四级递进机制：聚合诊断模式 → 提炼临床规律 → 注入知识图谱 → 生成知识条目 |
| 6 | **盲区自动补充** | 三引擎搜不到时自动发现知识盲区，搜索权威来源并写入知识库 |

---

## 4-Agent 架构

4 个 Specialist Agent 按**能力柱**划分，1 个 Coordinator Agent 负责协调：

| Agent | 颜色 | 能力柱 | 核心工具 |
|-------|------|--------|---------|
| **intake-specialist** | yellow | 问诊采集 | 9段式问诊、病历CRUD、OCR识别、实体抽取、红旗筛查 |
| **knowledge-specialist** | blue | 知识检索 | TOC+RAG+KG 三引擎搜索、盲区补充、视频知识库 |
| **analysis-specialist** | red | 智能分析 | 药物相互作用、化验解读、鉴别诊断、认知偏差检查 |
| **evolution-specialist** | green | 自我进化 | 四级递进、诊断模式追踪、KG注入、临床规律提炼 |
| **team-coordinator** | purple | 协调调度 | 7 个协调工具（dispatch/observe/proceed/revise/finish/assert/publish） |

### 协作模式

```
用户: "5岁孩子发烧38.5°C持续6h,轻微咳嗽"
   │
   ▼
team-coordinator (并行派发)
   │
   ├─→ intake-specialist    → 9段式问诊 + 建病历 + 实体抽取
   ├─→ knowledge-specialist → TOC+RAG+KG 搜"儿童发热" → 教材+图谱结果
   ├─→ analysis-specialist  → 药物安全 + 鉴别诊断 + 认知偏差检查
   └─→ evolution-specialist → 提取诊断模式 → 触发自进化
   │
   ▼
协调器综合 → 单一报告（含免责声明）
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| 智能体框架 | OpenHarness（Python，MIT 协议） |
| LLM 接口 | OpenAI-compatible API（支持 OpenRouter / DeepSeek / Qwen 等 12 种 Provider） |
| Web 后端 | FastAPI + uvicorn + WebSocket |
| Web 前端 | React 19 + Vite 6 + TypeScript 5.8 + Zustand 5 |
| 数据验证 | Pydantic v2 |
| 向量存储 | DuckDB |
| 知识图谱 | JSON（84K 实体 / 120K 关系） |
| CLI | Typer + Rich + Textual |

---

## 快速开始

```bash
# 1. 创建 conda 环境
conda create -n openharness python=3.11 -y
conda activate openharness

# 2. 克隆项目
git clone https://github.com/HKUDS/OpenHarness.git
cd OpenHarness

# 3. 安装依赖
pip install uv
uv pip install -e .

# 4. 配置 LLM
openharness setup

# 5. 迁移临床数据（详见部署手册）
# ...

# 6. 启动 WebUI
cd webui && npm install && npm run dev
```

完整部署步骤请参阅 [部署手册](docs/deployment.md)。

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [系统架构](docs/architecture.md) | 三层架构设计、4-Agent 详细说明、数据架构、WebUI 架构 |
| [开发进度](docs/progress.md) | V1→V2 演进、各模块状态、已知限制 |
| [部署手册](docs/deployment.md) | conda + uv 安装、数据迁移（直接复制/源构建）、WebUI 配置 |
| [未来计划](docs/roadmap.md) | 短期/中期/长期规划 |

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。

> ⚠️ 本系统仅供学习和研究用途，不构成专业医疗建议。
