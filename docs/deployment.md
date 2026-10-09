# 部署手册

## 前置条件

| 条件 | 要求 |
|------|------|
| 操作系统 | Ubuntu 20.04+ |
| Python | 3.10+ |
| Node.js | 18+ |
| 内存 | ≥ 4 GB（clinical-core 数据 145MB） |
| 磁盘 | ≥ 1 GB（项目 + 数据 + 依赖） |
| 网络 | 需访问 LLM API 端点（如 OpenRouter） |

---

## 方式一：conda + uv 部署（推荐）

### Step 1: 创建 conda 环境

```bash
conda create -n openharness python=3.11 -y
conda activate openharness
```

### Step 2: 安装 uv

```bash
pip install uv
```

### Step 3: 克隆项目

```bash
git clone https://github.com/HKUDS/OpenHarness.git
cd OpenHarness
```

### Step 4: 安装 Python 依赖

```bash
uv pip install -e .
```

如需开发依赖（pytest、ruff、mypy）：

```bash
uv pip install -e ".[dev]"
```

验证安装：

```bash
openharness --version
# 或
oh --version
```

### Step 5: 配置 LLM Provider

**方式 A：交互式配置**

```bash
openharness setup
```

按引导选择 workflow → 认证 → preset → 模型。

**方式 B：手动编辑配置文件**

```bash
mkdir -p ~/.openharness
cat > ~/.openharness/settings.json << 'EOF'
{
  "active_profile": "openrouter",
  "profiles": {
    "openrouter": {
      "provider": "openai",
      "api_format": "openai",
      "base_url": "http://YOUR_LLM_HOST:PORT/v1",
      "model": "YOUR_MODEL_NAME",
      "api_key": "YOUR_API_KEY",
      "max_tokens": 16384,
      "timeout": 30
    }
  },
  "permission_mode": "default",
  "memory_enabled": true
}
EOF
```

**方式 C：使用已有配置**

直接从源机器复制：

```bash
scp ~/.openharness/settings.json user@target:~/.openharness/
```

### Step 6: 迁移临床数据（直接复制）

**在源机器打包**：

```bash
# 打包 clinical-core（145MB）
cd ~/.openharness/skills/clinical-core
tar czf /tmp/clinical-core.tar.gz .

# 打包 4 个 protocol skill
cd ~/.openharness/skills
tar czf /tmp/protocol-skills.tar.gz \
  intake-protocol/ \
  hybrid-search-protocol/ \
  analysis-protocol/ \
  evolution-protocol/
```

**传输到目标机器**：

```bash
scp /tmp/clinical-core.tar.gz user@target:/tmp/
scp /tmp/protocol-skills.tar.gz user@target:/tmp/
```

**在目标机器解压**：

```bash
# clinical-core
mkdir -p ~/.openharness/skills/clinical-core
cd ~/.openharness/skills/clinical-core
tar xzf /tmp/clinical-core.tar.gz

# protocol skills
cd ~/.openharness/skills
tar xzf /tmp/protocol-skills.tar.gz
```

**验证数据完整性**：

```bash
# 检查关键文件存在
ls -lh ~/.openharness/skills/clinical-core/rag_knowledge.duckdb       # ~32 MB
ls -lh ~/.openharness/skills/clinical-core/knowledge_graph.json       # ~21 MB
ls -lh ~/.openharness/skills/clinical-core/knowledge_graph_index.json # ~19 MB
ls -lh ~/.openharness/skills/clinical-core/drug_interaction_db.json   # ~819 KB
ls ~/.openharness/skills/clinical-core/tools/hybrid_search.py
ls ~/.openharness/skills/clinical-core/knowledge/ | wc -l             # 应为 63
```

### Step 7: 部署 Agent 定义

```bash
# 在源机器
scp ~/.openharness/agents/intake-specialist.md user@target:~/.openharness/agents/
scp ~/.openharness/agents/knowledge-specialist.md user@target:~/.openharness/agents/
scp ~/.openharness/agents/analysis-specialist.md user@target:~/.openharness/agents/
scp ~/.openharness/agents/evolution-specialist.md user@target:~/.openharness/agents/
scp ~/.openharness/agents/team-coordinator.md user@target:~/.openharness/agents/
```

或批量打包：

```bash
# 源机器
tar czf /tmp/agents.tar.gz -C ~/.openharness/agents/ \
  intake-specialist.md knowledge-specialist.md \
  analysis-specialist.md evolution-specialist.md \
  team-coordinator.md
scp /tmp/agents.tar.gz user@target:/tmp/

# 目标机器
mkdir -p ~/.openharness/agents
cd ~/.openharness/agents
tar xzf /tmp/agents.tar.gz
```

### Step 8: 安装 WebUI 前端

```bash
cd OpenHarness/webui
npm install
```

如遇网络问题，可使用国内镜像：

```bash
npm install --registry=https://registry.npmmirror.com
```

### Step 9: 启动服务

**启动后端**：

```bash
# 确保在 conda 环境中
conda activate openharness
cd OpenHarness

# 后台启动（监听 0.0.0.0 以支持局域网访问）
nohup python -m webui.server.app > /tmp/openharness_webui.log 2>&1 &
echo $! > /tmp/openharness_webui.pid
```

**启动前端**：

```bash
cd OpenHarness/webui

# 开发模式（支持热更新）
npm run dev -- --host 0.0.0.0

# 或生产构建
npm run build
# 用静态服务器部署 dist/ 目录
npx serve dist -l 5173
```

**一键启动脚本**（可选）：

```bash
cat > /tmp/start_openharness.sh << 'SCRIPT'
#!/bin/bash
conda activate openharness
cd /path/to/OpenHarness

# 启动后端
nohup python -m webui.server.app > /tmp/openharness_webui.log 2>&1 &
echo $! > /tmp/openharness_webui.pid

# 等待后端就绪
sleep 3

# 启动前端
cd webui
npm run dev -- --host 0.0.0.0
SCRIPT
chmod +x /tmp/start_openharness.sh
```

### Step 10: 验证

```bash
# 1. API 验证 — 应返回 5 个 agent
curl -s http://localhost:8000/api/agents | python3 -c "
import sys, json
data = json.load(sys.stdin)
agents = data if isinstance(data, list) else data.get('agents', [])
for a in agents:
    print(f'  {a[\"name\"]:30s} color={a.get(\"color\",\"?\")}')
print(f'总计: {len(agents)} 个 agent')
"

# 2. Mock 模式测试
cd /path/to/OpenHarness
python scripts/multi_agent_team.py

# 3. 真实 LLM 测试
python scripts/multi_agent_team.py --real

# 4. WebUI 访问
# 浏览器打开 http://YOUR_SERVER_IP:5173
```

---

## 方式二：从 doctor_skills 源仓库构建

适用于需要从源数据重新构建 clinical-core 的场景。

### 前置：clone doctor_skills

```bash
git clone <doctor_skills-repo-url> ~/Myprojects/doctor_skills
```

### 构建步骤

```bash
SKILL_DIR=~/.openharness/skills/clinical-core
mkdir -p $SKILL_DIR/tools $SKILL_DIR/knowledge $SKILL_DIR/data

# 1. 复制 Python 工具脚本（25 个 .py）
cp ~/Myprojects/doctor_skills/tools/*.py $SKILL_DIR/tools/
# 注意：还需复制 toc_index.json（不在 *.py glob 中）
cp ~/Myprojects/doctor_skills/tools/toc_index.json $SKILL_DIR/tools/ 2>/dev/null || true

# 2. 复制 63 本教材
cp ~/Myprojects/doctor_skills/knowledge/*.md $SKILL_DIR/knowledge/

# 3. 复制检验参考数据
cp ~/Myprojects/doctor_skills/data/lab_reference.json $SKILL_DIR/data/

# 4. 构建药物相互作用数据库
cd $SKILL_DIR/tools
PYTHONIOENCODING=utf-8 python3 drug_interaction_db.py extract
# 产出：$SKILL_DIR/drug_interaction_db.json + drug_interaction_index.json

# 5. 构建 DuckDB 向量库（RAG）
PYTHONIOENCODING=utf-8 python3 rag_incremental.py
# 产出：$SKILL_DIR/rag_knowledge.duckdb

# 6. 复制知识图谱数据（40MB）
cp ~/Myprojects/doctor_skills/knowledge_graph.json $SKILL_DIR/
cp ~/Myprojects/doctor_skills/knowledge_graph_index.json $SKILL_DIR/
```

### 验证构建结果

```bash
# 验证工具
PYTHONIOENCODING=utf-8 python3 $SKILL_DIR/tools/hybrid_search.py "发热" --top 3
PYTHONIOENCODING=utf-8 python3 $SKILL_DIR/tools/kg_query.py "胸痛"
PYTHONIOENCODING=utf-8 python3 $SKILL_DIR/tools/drug_interaction_db.py stats

# 验证数据大小
du -sh $SKILL_DIR  # 应约 145 MB
```

---

## 局域网访问配置

### 后端（FastAPI / uvicorn）

编辑 `webui/server/app.py`，确保 uvicorn 监听所有网卡：

```python
uvicorn.run(app, host="0.0.0.0", port=8000)
```

### 前端（Vite）

编辑 `webui/vite.config.ts`：

```typescript
export default defineConfig({
  server: {
    host: "0.0.0.0",  // 监听所有网卡
    port: 5173,
    proxy: { ... }
  }
})
```

### 防火墙

```bash
# UFW
sudo ufw allow 5173/tcp
sudo ufw allow 8000/tcp

# 或 firewalld
sudo firewall-cmd --add-port=5173/tcp --permanent
sudo firewall-cmd --add-port=8000/tcp --permanent
sudo firewall-cmd --reload
```

### 生产部署建议

前端构建后用 nginx 反代：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态资源
    location / {
        root /path/to/OpenHarness/webui/dist;
        try_files $uri $uri/ /index.html;
    }

    # API + WebSocket 反代
    location ~ ^/(api|ws) {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```

```bash
# 构建前端
cd webui && npm run build
# 产出 dist/ 目录，由 nginx 托管
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENHARNESS_PROFILE` | `openrouter` | 当前使用的 provider profile 名 |
| `WEBUI_SPECIALIST_TIMEOUT_S` | `180` | 单个 specialist 执行超时（秒） |
| `WEBUI_SYNTHESIS_TIMEOUT_S` | `120` | 综合报告生成超时（秒） |
| `PYTHONIOENCODING` | — | 工具调用时必须设为 `utf-8` |
| `CLAUDE_CODE_COORDINATOR_MODE` | — | subprocess 中设为 `0` 防止协调器递归 |
| `MULTI_AGENT_REAL` | — | 设为 `1` 时 `multi_agent_team.py` 默认用真实 LLM |

---

## 故障排查

### `ModuleNotFoundError: No module named 'openharness'`

```bash
# 确保在 conda 环境中
conda activate openharness
# 确保项目已安装
uv pip install -e .
```

### `FileNotFoundError: rag_knowledge.duckdb`

clinical-core 数据未迁移。参考 [Step 6](#step-6-迁移临床数据直接复制) 或 [方式二](#方式二从-doctor_skills-源仓库构建)。

### `kg_query.py` 报错找不到 `knowledge_graph_index.json`

V2 新增的 KG 数据文件未复制：

```bash
cp /path/to/knowledge_graph.json ~/.openharness/skills/clinical-core/
cp /path/to/knowledge_graph_index.json ~/.openharness/skills/clinical-core/
```

### WebUI 无法从局域网访问

1. 确认 vite 和 uvicorn 都监听 `0.0.0.0`
2. 确认防火墙放行 5173 和 8000 端口
3. 确认云服务器安全组放行对应端口

### `drug_interaction_db.py` 报"数据库尚未构建"

```bash
cd ~/.openharness/skills/clinical-core/tools
PYTHONIOENCODING=utf-8 python3 drug_interaction_db.py extract
```

### 真实 LLM 测试超时

```bash
# 增加超时时间
python scripts/multi_agent_team.py --real --timeout 300
```

或检查 LLM API 端点是否可达：

```bash
curl http://YOUR_LLM_HOST:PORT/v1/models
```
