# Medical MultiAgent - Technical Architecture & Deep Dive

**[English](#english) | [中文](#中文)**

---

## English

### Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture Overview](#architecture-overview)
3. [Core Components](#core-components)
4. [Data Flow](#data-flow)
5. [Function Flow](#function-flow)
6. [File Structure & Responsibilities](#file-structure--responsibilities)
7. [Multi-Module Integration](#multi-module-integration)

---

### Project Overview

**Medical MultiAgent** is an advanced AI-powered personal agent system built on top of **OpenHarness**. It's a sophisticated framework for orchestrating multiple AI agents with specialized capabilities for medical and general-purpose tasks.

- **Version**: 0.1.9
- **Python**: ≥3.10
- **License**: MIT
- **Main Frameworks**: Anthropic API, OpenAI API, LiteLLM, MCP (Model Context Protocol)
- **Key Dependencies**: 
  - `anthropic>=0.40.0` - Claude AI models
  - `openai>=1.0.0` - OpenAI models
  - `textual>=0.80.0` - Terminal UI framework
  - `mcp>=1.0.0` - Protocol support
  - `websockets>=12.0` - Real-time communication
  - `slack-sdk`, `discord.py`, `python-telegram-bot` - Multi-channel support

---

### Architecture Overview

The system follows a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│              Frontend Layer (React Terminal)             │
│  - Terminal UI (TUI) built with Textual & React/TSX     │
│  - Web UI (optional)                                     │
└────────────────────┬────────────────────────────────────┘
                     │ (JSON + WebSocket)
┌────────────────────▼────────────────────────────────────┐
│           Runtime/Backend Host Layer                     │
│  - Async Runtime Management                             │
│  - Session Management                                   │
│  - Event Stream Processing                              │
│  - State Persistence                                    │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
┌───────▼──┐  ┌──────▼────┐  ┌───▼──────────┐
│  OHMO    │  │ OpenHarness
│ Personal │  │ Core Engine
│  Agent   │  │
└──────────┘  └────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
┌───────▼──┐  ┌──────▼────┐  ┌───▼──────────┐
│ Gateway  │  │ Skills &  │  │  Providers   │
│ Broker   │  │ Plugins   │  │  (LLM)       │
└──────────┘  └────────────┘  └──────────────┘
        │
  ┌─────┴─────┐
  │ Channels  │
  ├─────┬─────┼──────┬─────────┐
  │     │     │      │         │
┌─┴──┐ │ ┌────┴──┐ ┌─┴──┐ ┌───┴───┐
│Tg  │ │ │Slack  │ │Disc│ │Feishu │
└────┘ │ └───────┘ └────┘ └───────┘
       │
    ┌──┴──┐
    │API  │
    └─────┘
```

---

### Core Components

#### 1. **OHMO Module** (`ohmo/`)
The personal agent entry point and gateway service orchestrator.

**Key Files:**
- `cli.py` (25.8 KB) - Main CLI entry point with Typer framework
- `runtime.py` - Async runtime management and UI launching
- `workspace.py` - Workspace initialization and state management
- `memory.py` - Personal memory system for context persistence
- `session_storage.py` - Session history persistence
- `group_registry.py` - Group management for multi-user contexts
- `prompts.py` - System prompt construction

**Workspace Structure:**
```
~/.ohmo/
├── soul.md                 # Agent identity & personality
├── user.md                 # User profile & preferences
├── identity.md             # Agent shape/signature
├── BOOTSTRAP.md            # First-contact template
├── MEMORY.md               # Memory index
├── memory/                 # Personal memory files
├── skills/                 # Custom skill implementations
├── plugins/                # Plugin directory
├── groups/                 # Multi-agent group configs
├── sessions/               # Session history
├── logs/                   # Gateway logs
├── attachments/            # Uploaded files
├── state.json              # Runtime state
├── gateway.json            # Gateway configuration
└── gateway-restart-notice.json
```

**Memory System:**
- Type: `personal` | Domain: `preference`/`constraint`/`memory`
- Each entry has: ID, signature, created_at, updated_at, TTL, importance
- Supports deduplication via signature matching
- Thread-safe with file locks

---

#### 2. **OHMO Gateway Module** (`ohmo/gateway/`)
Handles multi-channel orchestration and agent pooling.

**Key Files:**
- `runtime.py` (49.4 KB) - Core gateway runtime & session pool management
- `service.py` (16.7 KB) - Gateway service lifecycle management
- `bridge.py` (16.4 KB) - Channel message bridging & routing
- `provider_commands.py` - LLM provider switching commands
- `group_tool.py` - Agent group management tools
- `notify.py` - Notification system
- `config.py` - Gateway configuration schema
- `models.py` - Data models
- `router.py` - Message routing logic

**Gateway Features:**
- **Multi-Channel Support**: Telegram, Slack, Discord, Feishu (Lark)
- **Session Routing**: `chat-thread` mode (maintains conversation per thread)
- **Permission Modes**: default, sandbox, isolated
- **Remote Administration**: Opt-in admin commands via channels
- **Progress Updates**: Real-time task execution feedback
- **Tool Hints**: Contextual help for available commands

**Configuration Schema:**
```json
{
  "provider_profile": "claude-api | openai-compatible",
  "enabled_channels": ["telegram", "slack"],
  "session_routing": "chat-thread",
  "send_progress": true,
  "send_tool_hints": true,
  "permission_mode": "default",
  "sandbox_enabled": false,
  "allow_remote_admin_commands": true,
  "allowed_remote_admin_commands": ["permissions", "plan"],
  "channel_configs": {
    "telegram": {
      "token": "...",
      "allow_from": ["user_id"],
      "reply_to_message": true
    },
    "slack": {
      "bot_token": "...",
      "app_token": "...",
      "mode": "socket",
      "reply_in_thread": true,
      "group_policy": "mention|open|allowlist"
    },
    "discord": {
      "token": "...",
      "gateway_url": "wss://gateway.discord.gg/?v=10&encoding=json",
      "intents": 513,
      "group_policy": "mention|open"
    },
    "feishu": {
      "domain": "https://open.feishu.cn",
      "app_id": "...",
      "app_secret": "...",
      "bot_names": ["ohmo", "openclaw"],
      "group_policy": "managed_or_mention|mention|open"
    }
  }
}
```

---

#### 3. **OpenHarness Core** (`src/openharness/`)
The foundational framework for multi-agent orchestration.

**Sub-Modules:**
- `api/` - RESTful API client interfaces
- `auth/` - Authentication & profile management (AuthManager)
- `autopilot/` - Autonomous task execution mode
- `bridge/` - Protocol bridges (MCP, WebSocket)
- `channels/` - Multi-platform integration adapters
- `commands/` - Command registry & execution
- `config/` - Configuration management
- `coordinator/` - Multi-agent coordination
- `engine/` - Core execution engine (async task processor)
- `hooks/` - Lifecycle hooks system
- `keybindings/` - Keyboard shortcuts for TUI
- `mcp/` - Model Context Protocol support
- `memory/` - Semantic memory & retrieval
- `output_styles/` - Terminal output formatting
- `permissions/` - RBAC system
- `personalization/` - User preference system
- `plugins/` - Plugin architecture
- `prompts/` - System prompt management
- `providers/` - LLM provider adapters
- `sandbox/` - Isolated execution environment
- `services/` - Microservice abstractions
- `skills/` - Skill registry & management
- `state/` - State machine & persistence
- `swarm/` - Agent swarm intelligence
- `tasks/` - Task scheduling & execution
- `themes/` - UI theme system
- `tools/` - Tool/function definitions
- `ui/` - UI components & lifecycle
- `utils/` - Utility functions
- `vim/` - Vim mode support
- `voice/` - Voice interface (optional)

**Main CLI Entry:** `src/openharness/cli.py` (91.7 KB)

---

### Data Flow

#### **Flow 1: User Input → Agent Processing → Output**

```
┌──────────────────────────────────────────────────────────────┐
│  User Input (Channel Message / Terminal Input)               │
│  ↓                                                            │
│  Channel Adapter (gateway/bridge.py)                         │
│  - Parse message (text, attachments, context)                │
│  - Enrich with user profile & permissions                    │
│  ↓                                                            │
│  Gateway Runtime (ohmo/gateway/runtime.py)                   │
│  - Route to appropriate session                              │
│  - Load user memory & session history                        │
│  - Construct augmented prompt                                │
│  ↓                                                            │
│  OpenHarness Engine (src/openharness/engine/)                │
│  - Parse tools from registry                                 │
│  - Execute via LLM provider                                  │
│  - Stream events (delta, progress, tool calls)               │
│  ↓                                                            │
│  Tool Executor (src/openharness/tools/)                      │
│  - Validate permissions (sandbox/isolation)                  │
│  - Execute skill/plugin/system tool                          │
│  - Capture output                                            │
│  ↓                                                            │
│  LLM Model (via provider: Claude/OpenAI)                     │
│  - Process tool result                                       │
│  - Generate response                                         │
│  ↓                                                            │
│  Output Formatter (gateway/notify.py)                        │
│  - Format response for each channel                          │
│  - Send to user across all channels                          │
│  ↓                                                            │
│  Session Storage (ohmo/session_storage.py)                   │
│  - Persist messages & metadata                               │
│  - Update memory if needed                                   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Key Data Structures:**
```python
# Message flow
message = {
    "role": "user|assistant",
    "content": str | list[{type, text|image_url|...}],
    "metadata": {
        "timestamp": datetime,
        "channel": "telegram|slack|...",
        "user_id": str,
        "session_id": str,
        "turn_index": int,
    }
}

# Tool call
tool_call = {
    "id": str,
    "type": "function",
    "function": {
        "name": str,
        "arguments": json_str,
    }
}

# Event stream
event = AssistantTextDelta | AssistantTurnComplete | ErrorEvent | StatusEvent | ...
```

---

#### **Flow 2: Session Persistence**

```
Runtime Session State → JSON Serialization
                     ↓
~/.ohmo/sessions/{cwd}/{session_id}.json
                     ↓
Load on Resume/Continue
```

#### **Flow 3: Memory Management**

```
User Input
   ↓
Semantic Search (optional)
   ↓
Memory Files (~/.ohmo/memory/*.md)
   ↓
Augment System Prompt
   ↓
LLM Processing
   ↓
[Memory Update Command] → Add/Remove/Modify Memory
   ↓
Persist to Disk with Signature Deduplication
```

---

### Function Flow

#### **A. CLI Initialization Flow** (`ohmo/cli.py`)

```python
main()  # Entry point
  ├─ If --continue: load latest session
  │   ├─ OhmoSessionBackend.load_latest()
  │   └─ Restore messages & tool metadata
  ├─ If --resume {id}: load specific session
  │   ├─ OhmoSessionBackend.load_by_id()
  │   └─ Restore messages & tool metadata
  ├─ If --print-mode: single-shot execution
  │   └─ run_ohmo_print_mode() → stdout
  ├─ If --backend-only: process in background
  │   └─ run_ohmo_backend() → async runtime
  └─ Default: interactive TUI
      └─ launch_ohmo_react_tui() → React Terminal UI

Subcommands:
  init       → initialize_workspace() + config wizard
  config     → _run_gateway_config_wizard()
  doctor     → workspace_health() + provider status
  memory *   → add/list/remove memory entries
  soul *     → show/edit soul.md
  user *     → show/edit user.md
  gateway *  → start/stop/restart/run/status gateway service
```

#### **B. Workspace Initialization** (`ohmo/workspace.py`)

```python
initialize_workspace(workspace: str|Path|None) -> Path
  ├─ ensure_workspace() → create directory structure
  │   ├─ mkdir ~/.ohmo/
  │   ├─ mkdir ~/.ohmo/memory/
  │   ├─ mkdir ~/.ohmo/skills/
  │   ├─ mkdir ~/.ohmo/plugins/
  │   ├─ mkdir ~/.ohmo/groups/
  │   ├─ mkdir ~/.ohmo/sessions/
  │   └─ mkdir ~/.ohmo/logs/
  ├─ Write template files if missing:
  │   ├─ soul.md (agent personality)
  │   ├─ user.md (user profile)
  │   ├─ identity.md (agent identity)
  │   └─ MEMORY.md (memory index)
  ├─ Initialize state.json
  │   ├─ bootstrap_seeded = True
  │   └─ Write BOOTSTRAP.md if fresh
  └─ Initialize gateway.json
      └─ Default provider, channels, permissions
```

#### **C. Gateway Configuration Flow** (`ohmo/cli.py`)

```python
_run_gateway_config_wizard() -> GatewayConfig
  ├─ _prompt_provider_profile()
  │   └─ Select from: claude-api, openai-compatible, etc.
  ├─ _prompt_channels()
  │   ├─ For each channel (telegram, slack, discord, feishu):
  │   │   ├─ Prompt: Enable?
  │   │   ├─ Prompt: allow_from (whitelist)
  │   │   └─ Channel-specific config:
  │   │       ├─ Telegram: token, reply_to_message
  │   │       ├─ Slack: bot_token, app_token, group_policy
  │   │       ├─ Discord: token, intents, group_policy
  │   │       └─ Feishu: app_id, app_secret, bot_names
  ├─ Prompt: send_progress?
  ├─ Prompt: send_tool_hints?
  ├─ Prompt: allow_remote_admin_commands?
  ├─ Save config to gateway.json
  └─ _maybe_restart_gateway() if running
```

#### **D. Runtime Execution** (`ohmo/runtime.py`)

```python
launch_ohmo_react_tui()
  ├─ Verify React frontend exists
  ├─ npm install (if needed)
  ├─ Build backend command
  ├─ Set OPENHARNESS_FRONTEND_CONFIG env var
  ├─ Spawn tsx process for React terminal UI
  └─ Await process completion

run_ohmo_backend()
  ├─ Initialize workspace
  ├─ Load extra skill/plugin directories
  ├─ build_runtime() → Bundle with:
  │   ├─ System prompt (from build_ohmo_system_prompt)
  │   ├─ LLM provider config
  │   ├─ Session backend
  │   ├─ Memory backend
  │   └─ Extra skill/plugin directories
  ├─ start_runtime() → async event loop
  ├─ Handle user input via handle_line()
  ├─ Render events (text deltas, errors, progress)
  └─ close_runtime()

run_ohmo_print_mode()
  ├─ Single prompt input
  ├─ Process without TUI
  ├─ Output to stdout
  └─ Return exit code
```

#### **E. Memory Operations** (`ohmo/memory.py`)

```python
add_memory_entry(workspace, title, content) -> Path
  ├─ Generate slug from title
  ├─ Compute signature (deduplication)
  ├─ Check existing entries
  ├─ Create/update memory file:
  │   ├─ Metadata (ID, created_at, updated_at, TTL, importance)
  │   └─ Body (content)
  ├─ Thread-safe with file lock
  ├─ Update MEMORY.md index
  └─ Return path

list_memory_files(workspace) -> List[Path]
  ├─ Scan memory directory
  ├─ Filter by active/valid entries
  └─ Return sorted list

remove_memory_entry(workspace, name) -> bool
  ├─ Find matching entry
  ├─ Soft-delete (mark disabled=True)
  ├─ Update metadata with new timestamp
  ├─ Remove from MEMORY.md index
  └─ Return success
```

#### **F. Gateway Runtime** (`ohmo/gateway/runtime.py`)

```python
OhmoSessionRuntimePool
  ├─ Manages multiple concurrent sessions
  ├─ Routes messages to correct session
  ├─ Pooling strategy:
  │   ├─ chat-thread: one session per conversation thread
  │   └─ direct: one session per user (direct messages)
  └─ Event aggregation:
      ├─ Collect per-session events
      ├─ Apply group policies (mention/open/allowlist)
      └─ Format for each channel

Channel Bridges (gateway/bridge.py)
  ├─ Telegram:
  │   ├─ Webhook listener
  │   ├─ Parse updates
  │   └─ Reply to message if configured
  ├─ Slack:
  │   ├─ Socket mode listener
  │   ├─ Parse events
  │   └─ Reply in thread if configured
  ├─ Discord:
  │   ├─ WebSocket gateway connection
  │   ├─ Parse intents
  │   └─ Post to channel
  └─ Feishu:
      ├─ Event webhook listener
      ├─ Parse events with signature validation
      └─ Post with @ mentions
```

---

### File Structure & Responsibilities

| Path | Size | Purpose |
|------|------|---------|
| `ohmo/cli.py` | 25.8 KB | Main CLI with Typer; handles init/config/memory/gateway commands |
| `ohmo/runtime.py` | 7.8 KB | Async runtime builders; TUI/print/backend launchers |
| `ohmo/workspace.py` | 10.5 KB | Workspace initialization, path management, templates |
| `ohmo/memory.py` | 8.2 KB | Personal memory CRUD, deduplication, file locking |
| `ohmo/session_storage.py` | 7.0 KB | Session history persistence & loading |
| `ohmo/group_registry.py` | 2.8 KB | Multi-agent group management |
| `ohmo/prompts.py` | 2.2 KB | System prompt construction |
| `ohmo/gateway/runtime.py` | 49.4 KB | Core gateway logic, session pool, stream processing |
| `ohmo/gateway/service.py` | 16.7 KB | Gateway lifecycle (start/stop/status), process management |
| `ohmo/gateway/bridge.py` | 16.4 KB | Channel message routing (Telegram, Slack, Discord, Feishu) |
| `ohmo/gateway/provider_commands.py` | 6.5 KB | Provider switching tools |
| `ohmo/gateway/group_tool.py` | 6.8 KB | Agent group management tools |
| `ohmo/gateway/notify.py` | 3.1 KB | Notification dispatcher |
| `ohmo/gateway/config.py` | 1.5 KB | Config schema validation |
| `src/openharness/cli.py` | 91.7 KB | OpenHarness CLI (autopilot, skills, plugins, etc.) |
| `src/openharness/platforms.py` | 2.7 KB | Platform detection & capabilities |
| `tests/` | Various | Comprehensive test suites for all modules |

---

### Multi-Module Integration

#### **Integration Point 1: CLI → Runtime → Engine**

```
ohmo/cli.py (main)
    ↓
ohmo/runtime.py (build_runtime)
    ↓
openharness.ui.runtime (build_runtime)
    ↓
openharness.engine (EngineRuntime)
    ↓
openharness.providers (LLMProvider)
    ↓
anthropic.client OR openai.client (API call)
```

#### **Integration Point 2: Memory → Prompt → LLM**

```
ohmo/memory.py (load_memory_prompt)
    ↓
ohmo/prompts.py (build_ohmo_system_prompt)
    ↓
openharness.engine.execute
    ↓
LLM Context Window
    ├─ System prompt
    ├─ User profile (user.md)
    ├─ Agent identity (soul.md)
    ├─ Recent memory files
    ├─ Session history
    └─ Current message
```

#### **Integration Point 3: Gateway → Channels → Responses**

```
ohmo/gateway/runtime.py (OhmoSessionRuntimePool)
    ├─ openharness.engine (process message)
    ├─ Stream events
    └─ ohmo/gateway/bridge.py (format & send)
        ├─ Telegram adapter
        ├─ Slack adapter
        ├─ Discord adapter
        └─ Feishu adapter
```

#### **Integration Point 4: Permissions → Execution**

```
User message
    ↓
ohmo/gateway/bridge.py (extract user_id, channel, context)
    ↓
openharness.permissions (check RBAC)
    ├─ Is user allowed?
    ├─ Is tool allowed?
    └─ Sandbox constraints?
    ↓
openharness.sandbox (isolated execution if needed)
    ↓
Tool execution with captured output
```

---

### Key Execution Scenarios

#### **Scenario 1: Fresh Setup**
```bash
$ ohmo init --interactive
→ initialize_workspace()
→ _run_gateway_config_wizard()
→ Select provider profile
→ Configure channels (Telegram, Slack, etc.)
→ Save to gateway.json
→ Start interactive session or exit
```

#### **Scenario 2: Message from Slack**
```
1. Slack app receives message
2. Webhook → ohmo/gateway/bridge.py (SlackChannelAdapter)
3. Parse message, user_id, thread_id
4. Route to OhmoSessionRuntimePool
5. Load session for this thread
6. Augment with memory & context
7. Call openharness.engine
8. LLM processes tools
9. Format response
10. Post back to Slack thread
11. Persist to session history
```

#### **Scenario 3: Resume Session**
```bash
$ ohmo --continue
→ Load latest session from sessions/
→ Restore messages[] and tool_metadata
→ Continue from last turn
→ Persist new messages
```

#### **Scenario 4: Memory Update During Conversation**
```
User: "Remember, I prefer async code"
LLM detects intent → calls /memory add
→ add_memory_entry(workspace, "code_preference", "I prefer async")
→ Compute signature for deduplication
→ Write to memory/code_preference.md
→ Update MEMORY.md index
→ Next session includes this in context
```

---

## 中文

### 项目概述

**Medical MultiAgent** 是一个构建在 **OpenHarness** 框架之上的高级 AI 多智能体系统。它提供了一个完整的个人助手框架，支持多个 LLM 提供商、多频道集成和灵活的技能扩展。

- **版本**: 0.1.9
- **Python**: ≥3.10
- **许可证**: MIT
- **核心依赖**: Anthropic API, OpenAI API, MCP (模型上下文协议), WebSockets

---

### 架构概览

系统采用分层架构设计：

```
┌──────────────────────────────────────────────┐
│        前端层 (React 终端 UI)                  │
│  - Textual 终端 UI                          │
│  - 可选的 Web UI                             │
└────────────────┬─────────────────────────────┘
                 │ (JSON + WebSocket)
┌────────────────▼─────────────────────────────┐
│      运行时/后端主机层                        │
│  - 异步运行时管理                            │
│  - 会话管理                                  │
│  - 事件流处理                                │
│  - 状态持久化                                │
└────────────────┬─────────────────────────────┘
                 │
      ┌──────────┼──────────┐
      │          │          │
   ┌──▼─┐    ┌──▼──┐   ┌───▼─────┐
   │OHMO│    │OpenH│   │Gateway  │
   │    │    │ness │   │Broker   │
   └─────┘    └─────┘   └─────────┘
```

---

### 核心组件详解

#### **1. OHMO 模块** (`ohmo/`)
个人助手的主要入口和网关服务编排器。

**工作区结构** (`~/.ohmo/`)：
- `soul.md` - 助手的灵魂与人格
- `user.md` - 用户的个人资料与偏好
- `identity.md` - 助手的身份标签
- `BOOTSTRAP.md` - 首次启动模板
- `memory/` - 持久化记忆存储
- `skills/` - 自定义技能
- `plugins/` - 插件目录
- `sessions/` - 会话历史
- `gateway.json` - 网关配置

**记忆系统特点**：
- 自动去重（通过签名匹配）
- TTL 支持（过期清理）
- 重要性等级
- 线程安全（文件锁）
- 支持禁用而非删除

#### **2. OHMO 网关模块** (`ohmo/gateway/`)
多频道消息路由和智能体池管理。

**支持的频道**：
- Telegram （即时通讯）
- Slack （团队协作）
- Discord （社区）
- Feishu/Lark （企业通讯）

**网关配置关键项**：
```json
{
  "provider_profile": "claude-api 或 openai-compatible",
  "enabled_channels": ["telegram", "slack"],
  "session_routing": "chat-thread 或 direct",
  "permission_mode": "default|sandbox|isolated",
  "send_progress": true,
  "send_tool_hints": true,
  "allow_remote_admin_commands": true
}
```

#### **3. OpenHarness 核心** (`src/openharness/`)
多智能体编排的基础框架，包含：
- API 客户端接口
- 身份认证管理
- 自主执行模式
- 多协议适配
- 技能与插件系统
- 权限管理
- 状态机
- 智能体集群

---

### 数据流详解

#### **流程 1: 用户输入 → 处理 → 输出**

```
用户输入 (频道消息或终端输入)
    ↓
频道适配器 (gateway/bridge.py)
    ├─ 解析消息内容
    ├─ 提取用户信息
    └─ 验证权限
    ↓
网关运行时 (ohmo/gateway/runtime.py)
    ├─ 路由到对应会话
    ├─ 加载用户记忆
    └─ 构建增强提示词
    ↓
OpenHarness 引擎
    ├─ 解析可用工具
    ├─ 调用 LLM
    └─ 流式处理事件
    ↓
工具执行器
    ├─ 权限检查
    ├─ 沙箱执行
    └─ 捕获输出
    ↓
响应格式化与发送
    ├─ 格式化每个频道的输出
    └─ 发送到用户
    ↓
会话持久化 (ohmo/session_storage.py)
    ├─ 保存消息历史
    └─ 更新记忆（如需）
```

**关键数据结构**：

```python
# 消息对象
{
    "role": "user|assistant",
    "content": "...",
    "metadata": {
        "timestamp": "...",
        "channel": "telegram|slack|...",
        "user_id": "...",
        "session_id": "..."
    }
}

# 工具调用
{
    "id": "...",
    "type": "function",
    "function": {
        "name": "tool_name",
        "arguments": "{...}"
    }
}
```

#### **流程 2: 记忆管理**

```
用户消息
    ↓
触发记忆更新命令 (/memory add)
    ↓
计算签名（用于去重）
    ↓
写入 ~/.ohmo/memory/{name}.md
    ↓
更新 MEMORY.md 索引
    ↓
下一次对话自动加载到上下文中
```

#### **流程 3: 会话持久化**

```
内存中的运行时状态
    ↓
JSON 序列化
    ↓
保存到 ~/.ohmo/sessions/{cwd}/{session_id}.json
    ↓
恢复时重新加载消息和工具元数据
```

---

### 函数调用流

#### **A. CLI 初始化流** (`ohmo/cli.py`)

```python
main()  # 主入口
  ├─ 若 --continue: 加载最新会话
  ├─ 若 --resume {id}: 加载指定会话
  ├─ 若 --print: 单次执行并输出
  ├─ 若 --backend-only: 后台执行
  └─ 默认: 启动交互式终端 UI

子命令:
  init      → 初始化工作区 + 配置向导
  config    → 运行网关配置向导
  doctor    → 诊断工作区和提供商状态
  memory *  → 添加/列表/删除记忆条目
  soul *    → 显示/编辑 soul.md
  user *    → 显示/编辑 user.md
  gateway * → 启动/停止/重启/运行/状态 网关服务
```

#### **B. 工作区初始化** (`ohmo/workspace.py`)

```python
initialize_workspace(workspace)
  ├─ 创建目录结构
  │   ├─ ~/.ohmo/
  │   ├─ ~/.ohmo/memory/
  │   ├─ ~/.ohmo/skills/
  │   ├─ ~/.ohmo/plugins/
  │   ├─ ~/.ohmo/sessions/
  │   └─ ~/.ohmo/logs/
  ├─ 写入模板文件（如果缺失）
  │   ├─ soul.md
  │   ├─ user.md
  │   ├─ identity.md
  │   └─ MEMORY.md
  ├─ 初始化 state.json
  └─ 初始化 gateway.json（默认配置）
```

#### **C. 网关配置流** (`ohmo/cli.py`)

```python
_run_gateway_config_wizard()
  ├─ 选择 LLM 提供商
  │   (claude-api, openai-compatible, etc.)
  ├─ 配置各个频道
  │   ├─ Telegram: token, allow_from, reply_to_message
  │   ├─ Slack: bot_token, app_token, group_policy
  │   ├─ Discord: token, intents, group_policy
  │   └─ Feishu: app_id, app_secret, bot_names
  ├─ 是否发送进度更新?
  ├─ 是否发送工具提示?
  ├─ 是否允许远程管理命令?
  ├─ 保存配置到 gateway.json
  └─ 若网关运行中，询问是否重启
```

#### **D. 运行时执行** (`ohmo/runtime.py`)

```python
launch_ohmo_react_tui()
  ├─ 验证 React 前端存在
  ├─ npm install（如需）
  ├─ 设置环境变量
  └─ 启动 tsx 进程（React 终端 UI）

run_ohmo_backend()
  ├─ 初始化工作区
  ├─ 加载额外的技能和插件目录
  ├─ 构建运行时 Bundle
  │   ├─ 系统提示词
  │   ├─ LLM 提供商配置
  │   ├─ 会话后端
  │   ├─ 记忆后端
  │   └─ 技能/插件目录
  ├─ 启动异步事件循环
  ├─ 处理用户输入
  ├─ 渲染事件流
  └─ 关闭运行时
```

#### **E. 记忆操作** (`ohmo/memory.py`)

```python
add_memory_entry(workspace, title, content)
  ├─ 从标题生成 slug
  ├─ 计算签名（去重）
  ├─ 检查是否已存在
  ├─ 创建/更新记忆文件
  │   ├─ 元数据（ID, 创建时间, 更新时间, TTL, 重要性）
  │   └─ 内容
  ├─ 文件锁（线程安全）
  ├─ 更新 MEMORY.md 索引
  └─ 返回文件路径

list_memory_files(workspace)
  ├─ 扫描记忆目录
  ├─ 过滤活跃条目
  └─ 返回排序列表

remove_memory_entry(workspace, name)
  ├─ 查找匹配条目
  ├─ 软删除（标记为禁用）
  ├─ 更新元数据
  ├─ 从索引中删除
  └─ 返回是否成功
```

---

### 文件责任矩阵

| 文件路径 | 大小 | 主要责任 |
|--------|------|---------|
| `ohmo/cli.py` | 25.8 KB | Typer CLI 主入口；init/config/memory/gateway 命令 |
| `ohmo/runtime.py` | 7.8 KB | 异步运行时构建器；TUI/print/backend 启动器 |
| `ohmo/workspace.py` | 10.5 KB | 工作区初始化、路径管理、模板 |
| `ohmo/memory.py` | 8.2 KB | 记忆的 CRUD、去重、文件锁 |
| `ohmo/session_storage.py` | 7.0 KB | 会话历史持久化与加载 |
| `ohmo/gateway/runtime.py` | 49.4 KB | 核心网关逻辑、会话池、流处理 |
| `ohmo/gateway/service.py` | 16.7 KB | 网关生命周期（启动/停止/状态）、进程管理 |
| `ohmo/gateway/bridge.py` | 16.4 KB | 频道消息路由（Telegram, Slack, Discord, Feishu） |
| `src/openharness/cli.py` | 91.7 KB | OpenHarness CLI（自动驾驶、技能、插件等） |
| `tests/` | 多个 | 全面的测试套件 |

---

### 典型执行场景

#### **场景 1: 首次设置**
```bash
$ ohmo init --interactive
→ initialize_workspace()
→ 运行网关配置向导
→ 选择 LLM 提供商
→ 配置频道（Telegram、Slack 等）
→ 保存配置到 gateway.json
→ 启动交互会话或退出
```

#### **场景 2: 收到 Slack 消息**
```
1. Slack 应用收到消息
2. 网钩 → ohmo/gateway/bridge.py (SlackChannelAdapter)
3. 解析消息、用户 ID、线程 ID
4. 路由到 OhmoSessionRuntimePool
5. 为该线程加载会话
6. 使用记忆和上下文增强
7. 调用 openharness.engine
8. LLM 处理工具调用
9. 格式化响应
10. 发回到 Slack 线程
11. 持久化到会话历史
```

#### **场景 3: 恢复会话**
```bash
$ ohmo --continue
→ 加载最新的会话快照
→ 恢复消息[] 和工具元数据
→ 从上一轮继续
→ 保存新消息
```

#### **场景 4: 对话中的记忆更新**
```
用户: "记住，我喜欢异步代码"
LLM 检测到意图 → 调用 /memory add
→ add_memory_entry(workspace, "code_preference", "...")
→ 计算签名（去重）
→ 写入 memory/code_preference.md
→ 更新 MEMORY.md 索引
→ 下一个会话自动加载到上下文中
```

---

### 多模块集成点

#### **集成点 1: CLI → 运行时 → 引擎**
```
ohmo/cli.py (main)
    ↓
ohmo/runtime.py (build_runtime)
    ↓
openharness.ui.runtime (构建)
    ↓
openharness.engine (执行)
    ↓
openharness.providers (LLM 提供商)
    ↓
Anthropic / OpenAI API 调用
```

#### **集成点 2: 记忆 → 提示词 → LLM**
```
ohmo/memory.py (加载记忆)
    ↓
ohmo/prompts.py (构建系统提示词)
    ↓
openharness.engine.execute
    ↓
LLM 上下文窗口
    ├─ 系统提示词
    ├─ 用户资料
    ├─ 助手身份
    ├─ 最近记忆
    ├─ 会话历史
    └─ 当前消息
```

#### **集成点 3: 网关 → 频道 → 响应**
```
ohmo/gateway/runtime.py (OhmoSessionRuntimePool)
    ├─ openharness.engine (处理消息)
    ├─ 流式事件
    └─ ohmo/gateway/bridge.py (格式化和发送)
        ├─ Telegram 适配器
        ├─ Slack 适配器
        ├─ Discord 适配器
        └─ Feishu 适配器
```

#### **集成点 4: 权限 → 执行**
```
用户消息
    ↓
ohmo/gateway/bridge.py (提取用户、频道、上下文)
    ↓
openharness.permissions (RBAC 检查)
    ├─ 用户被允许?
    ├─ 工具被允许?
    └─ 沙箱约束?
    ↓
openharness.sandbox (必要时隔离执行)
    ↓
工具执行与输出捕获
```

---

### 快速参考：关键命令

```bash
# 初始化
ohmo init --interactive

# 配置
ohmo config

# 诊断
ohmo doctor

# 记忆管理
ohmo memory list
ohmo memory add "标题" "内容"
ohmo memory remove "name"

# 编辑灵魂和用户资料
ohmo soul show
ohmo soul edit --set "新内容"
ohmo user show
ohmo user edit --set "新内容"

# 网关管理
ohmo gateway run          # 前台运行
ohmo gateway start        # 后台启动
ohmo gateway stop         # 停止
ohmo gateway restart      # 重启
ohmo gateway status       # 查看状态

# 会话控制
ohmo --print "单次提示"           # 单次执行
ohmo --continue                  # 继续最新会话
ohmo --resume {session_id}       # 恢复指定会话
ohmo --model gpt-4               # 覆盖模型
ohmo --max-turns 10              # 限制轮数
```

---

## 总结 / Summary

这个项目是一个**高度模块化的多智能体框架**，强调：

1. **工作区隔离** - 每个用户有独立的 `~/.ohmo` 工作区
2. **多频道支持** - 通过网关支持 Telegram、Slack、Discord、Feishu
3. **持久化记忆** - 自动去重的长期记忆系统
4. **会话管理** - 支持恢复和继续之前的对话
5. **灵活扩展** - 支持自定义技能、插件和 LLM 提供商
6. **权限隔离** - 基于角色的访问控制和沙箱执行

**关键设计原则**：
- 异步优先（全 async/await）
- 线程安全（文件锁、状态隔离）
- 事件驱动（流式处理）
- 模块化（清晰的依赖图）
- 可测试（广泛的测试覆盖）

---

*Generated with detailed analysis of the complete codebase structure*
