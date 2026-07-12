# agent-core 学习指南：从入门到架构理解

> 适用读者：有基础 Python 能力，想理解 Agent 框架底层原理
> 阅读方式：按章节顺序，每章对应一个模块，代码和解释交替

---

## 目录

1. [概述：这个项目是什么](#1-概述这个项目是什么)
2. [main.py：装配线](#2-mainpy装配线)
3. [loop.py：Agent 主循环](#3-looppyagent-主循环)
4. [ContextOrchestrator：上下文总调度器](#4-contextorchestrator上下文总调度器)
5. [MCP Client：外部工具接入](#5-mcp-client外部工具接入)
6. [Intent Classification：意图路由](#6-intent-classification意图路由)
7. [Memory Core：记忆内核](#7-memory-core记忆内核)
8. [Memory 检索 (M7)：三通道混合搜索](#8-memory-检索-m7三通道混合搜索)
9. [压缩管线 (M3)：三级压缩 + 熔断](#9-压缩管线-m3三级压缩--熔断)
10. [Context Selection (M4)：上下文选择](#10-context-selection-m4上下文选择)
11. [Eval 评估系统](#11-eval-评估系统)
12. [整体架构回顾](#12-整体架构回顾)

---

## 1. 概述：这个项目是什么

**agent-core** 是一个教学级 Agent 框架，逐模块实现了 Claude Code 的核心架构。

它不是什么：
- ❌ 不是 LangChain 替代品
- ❌ 不是生产级框架
- ❌ 不是追求性能最优

它是什么：
- ✅ 每个模块可以独立阅读、理解、修改
- ✅ 展示了 Agent 框架的完整链路：用户输入 → LLM调用 → 工具执行 → 返回
- ✅ 包含了工业级 Agent 需要的大部分子系统

**核心数据流**（一句话版）：

```
用户输入 → Hook拦截 → 意图分类 → 上下文组装 → LLM调用 → 工具执行 → Hook审计 → 返回
              ↑                          ↑                      ↑
         可注入上下文              压缩+选择+记忆           可阻止/修改
```

---

## 2. main.py：装配线

**文件**：`main.py`（约 600 行）

**角色**：整个系统的入口，负责"装配"而非"执行"。它创建所有对象、注册所有工具、连接所有子系统，但实际的 Agent 循环在 `loop.py` 里。

### 2.1 运行流程

```python
# 第一步：加载配置
load_dotenv()                        # .env → 环境变量
client = Anthropic(base_url=...)     # API 客户端（DeepSeek 兼容端点）
config = load_config(WORKDIR)        # settings.json → dict

# 第二步：启动外部服务
MCP_MGR = load_mcp_from_config(config)  # 读取 mcp_servers 配置
MCP_MGR.start_all()                     # 启动所有 MCP 服务器进程

# 第三步：创建意图分类器
INTENT_CLASSIFIER = IntentClassifier(mode="keyword")  # 默认 0 token 模式

# 第四步：创建全局单例（每个都是独立模块，后面逐个讲）
TODO = TodoManager()          # 待办事项
SKILLS = SkillLoader(...)     # 技能加载
TASK_MGR = TaskManager(...)   # 持久化任务
BUS = MessageBus(...)         # 消息总线
SCRATCHPAD = Scratchpad()     # 跨 Agent 共享记事本
STORE = Store(...)            # 持久化键值存储
SESSION = SessionState(...)   # 会话恢复
BG = BackgroundManager()      # 后台任务管理器

# 第五步：注册工具（Agent 可调用的"函数"）
_register_tools()             # 内置工具 15 个
MCP_MGR.register_tools(registry)  # MCP 工具动态注册

# 第六步：初始化 Memory OS（M6-M10）
memory_core = MemoryCore(db_path=...)    # 创建内核
memory_core.load()                       # 从磁盘恢复
retrieval_engine = memory_core.init_retrieval()   # M7 检索
importance_engine = memory_core.init_importance() # M8 动态打分
intelligence_engine = memory_core.init_intelligence(llm_call=...)  # M9 自动学习
lifecycle_engine = memory_core.init_lifecycle(llm_call=...)        # M10 生命周期

# 第七步：初始化 Context Engine（M1-M5）
orchestrator = ContextOrchestrator(
    store=STORE,
    base_system=SYSTEM,
    workspace=workspace,
    budget_manager=budget_mgr,
    compression_pipeline=compress_pipeline,
    selection_pipeline=selection_pipeline,
    ...
)

# 第八步：REPL 循环
while True:
    query = input("s_full >> ")         # 读用户输入
    orchestrator.add_message("user", query)  # 加入对话历史
    agent_loop(history, registry, client,
              orchestrator=orchestrator, ...)  # 执行
```

### 2.2 关键设计点

**装配 vs 执行分离**：`main.py` 只做装配，`loop.py` 只做执行。这让你可以单独测试任一方。

**MCP 动态工具注册**：MCP 工具是在运行时从外部服务器拉取的，不是在代码里写死的。注册后的工具名格式是 `mcp_<server>_<tool>`。

**意图路由 + MCP 联动**：
```python
# 从 MCP 服务器获取的所有工具，自动加入 web_search 意图
_web_tools = []
for name in MCP_MGR.get_all_tools():
    for t in MCP_MGR.get_all_tools()[name]:
        mcp_name = f"mcp_{name}_{t['name']}".replace("-", "_")
        _web_tools.append(mcp_name)
INTENT_CLASSIFIER.routes["web_search"] = _web_tools
```

这意味着当用户搜索网页时，只有 MCP 工具被发送给 LLM，bash/edit 等危险工具不会被发送。

---

## 3. loop.py：Agent 主循环

**文件**：`src/agent/loop.py`（约 400 行）

**角色**：Agent 的核心执行引擎。这是理解 Agent 工作原理最关键的文件。

### 3.1 主循环的结构

```python
def agent_loop(messages, tools_registry, client, *, orchestrator=None, ...):
    # ── 初始化 ──
    hm = hook_manager                     # Hook 管理器
    messages = orchestrator.get_messages()  # 如果用了 Orchestrator，接管消息列表

    # ▶ SessionStart hook（只执行一次）
    hm.execute("SessionStart", ...)

    # 构建初始系统提示词
    system = orchestrator.build_prompt()

    # ── 主循环 ──
    while True:

        # ① 压缩检查（如果上下文太长）
        orchestrator.tick()

        # ② 重建系统提示词（因为 Store 里的目标/事实可能变了）
        system = orchestrator.build_prompt()

        # ③ 收后台通知 + 检查收件箱
        notifs = bg_drain_fn()    # 后台任务完成的通知
        inbox = inbox_check_fn()  # 其他 Agent 发来的消息

        # ④ 意图分类 → 过滤工具列表
        intent = classify_intent_fn(last_user_message)
        tools = filter_tools_fn(intent, all_tools)
        # 例："搜索代码" → 只发送 grep/glob/read_file，不发 bash/edit

        # ⑤ LLM 调用
        response = client.messages.create(
            model=model, system=system,
            messages=messages, tools=tools,
            max_tokens=8000,
        )

        # ⑥ 如果 LLM 说完了（不是工具调用）
        if response.stop_reason != "tool_use":
            # ▶ Stop hook（可以强制继续，exit_code=2）
            break

        # ⑦ 执行工具
        for block in response.content:
            if block.type != "tool_use":
                continue

            # ▶ PreToolUse hook（可以阻止此工具）
            pre_result = hm.execute("PreToolUse", ...)
            if pre_result.is_blocked:
                continue  # 跳过被阻止的工具

            # 执行
            output = tools_registry.execute(tool_name, **tool_input)

            # ▶ PostToolUse hook（审计/后处理）
            hm.execute("PostToolUse", ...)

            # ▶ M2 事件：通知 Orchestrator
            if tool_name == "read_file":
                orchestrator.on_file_read(path, content)
            elif tool_name in ("edit_file", "write_file"):
                orchestrator.on_file_write(path)

        # ⑧ 把工具结果追加到对话历史
        messages.append({"role": "user", "content": tool_results})

        # 回到 ①
```

### 3.2 五个 Hook 插入点

```
SessionStart ────→ 会话开始，只执行一次
    │
UserPromptSubmit → 每次用户输入，可注入附加上下文
    │
PreToolUse ──────→ 每个工具执行前，可阻止（exit_code=2）
    │
PostToolUse ─────→ 每个工具执行后，审计/记录
    │
Stop ────────────→ LLM 返回最终回复时，可强制继续（exit_code=2）
```

### 3.3 两条执行路径

```
agent_loop 有两种运行模式：

模式 A：有 Orchestrator（新架构，M1+）
  orchestrator.tick()       → 压缩
  orchestrator.build_prompt() → 组装系统提示词
  orchestrator.add_message()  → 追加消息

模式 B：无 Orchestrator（旧架构，向后兼容）
  直接操作 messages[] 列表
  直接调用 collapse.py / auto.py
  直接拼接系统提示词
```

### 3.4 子 Agent

```python
def run_subagent(prompt, tools_registry, client, model, agent_type, max_turns):
    # 三层工具过滤
    restriction = get_agent_tool_restriction(agent_type)
    sub_tools = filter_tools_for_agent(all_tools, agent_type, ...)

    # 裸循环：无 Hook、无压缩、无后台
    for _ in range(max_turns):
        resp = client.messages.create(...)
        if resp.stop_reason != "tool_use":
            break
        for block in resp.content:
            output = tool.execute(**block.input)
        sub_msgs.append({"role": "user", "content": tool_results})
```

子 Agent 是"轻量执行器"——没有 Hook、压缩、意图路由、后台通知。

---

## 4. ContextOrchestrator：上下文总调度器

**文件**：`src/context/orchestrator.py`（约 450 行）

**角色**：所有上下文操作的唯一入口。从 M1 开始，agent_loop 不再直接触碰 messages[] 列表，一切通过 Orchestrator。

### 4.1 为什么要这个？

**问题**：旧架构中，agent_loop 直接操作 `messages[]`、直接调用压缩函数、直接拼接系统提示词。每加一个功能（workspace 视图、文件缓存、记忆注入），都要改 loop.py。

**解决**：引入 Orchestrator 作为中间层。loop.py 只知道"添加消息"和"构建提示词"，不知道内部怎么做的。

```
旧架构：
  loop.py → messages[] (直接操作)
  loop.py → collapse.py (直接调用)
  loop.py → "You are an agent..." (直接拼接)

新架构：
  loop.py → orchestrator.add_message() ──→ ConversationLayer
  loop.py → orchestrator.tick()        ──→ Budget→Policy→Pipeline
  loop.py → orchestrator.build_prompt()──→ Collect→Rank→Select→Pack→Build
```

### 4.2 内部结构

```python
class ContextOrchestrator:
    def __init__(self, ...):
        # ── 核心组件 ──
        self.store = Store()                    # 持久化键值存储
        self._conversation = ConversationLayer() # 对话历史
        self._instruction = InstructionLayer()   # 系统提示词

        # ── M2：工作区感知 ──
        self._workspace = WorkspaceLayer()       # 当前目录、Git 状态、打开文件
        self._file_cache = FileCacheLayer()      # 最近读取的文件缓存

        # ── M3：压缩框架 ──
        self._budget_mgr = BudgetManager()       # Token 预算管理
        self._policy = CompressionPolicy()        # 压缩决策
        self._pipeline = CompressionPipeline()    # 压缩执行（Tier1→2→3）
        self._circuit_breaker = CircuitBreaker()  # 熔断器

        # ── M4：上下文选择 ──
        self._selection_pipeline = SelectionPipeline()  # Collect→Rank→Select→Pack

        # ── M6：记忆 ──
        self._memory = MemoryLayer()             # 记忆注入层

        # ── Layer Registry：可动态扩展 ──
        self._layers = {}        # {name: layer}
        self._layer_order = []   # 组装顺序
        self._builder = PromptBuilder()  # 把所有层拼成最终提示词
```

### 4.3 Layer Registry 模式

```python
# 注册层的顺序决定了它们在 prompt 中的顺序
self.register_layer(instruction_layer, position=0)   # 最前面
self.register_layer(workspace_layer, position=1)     # 工作区信息
self.register_layer(file_cache_layer, position=2)    # 文件缓存
self.register_layer(memory_layer, position=3)        # 记忆搜索结果
self.register_layer(summary_layer, position=4)       # 压缩摘要
self.register_layer(conversation_layer)              # 最后面（追加）

# 以后加新层，一行代码：
orch.register_layer(scratchpad_layer, position=3)
```

### 4.4 build_prompt() 的两条路径

```python
def build_prompt(self):
    if self._selection_pipeline:        # M4 路径（新）
        # Collect → Rank → Select → Pack → build_from_package
        ctx = SelectionContext()
        for layer in self.iter_layers():
            setattr(ctx, layer.name, layer)
        sel_result = self._selection_pipeline.run(ctx)
        return self._builder.build_from_package(sel_result.package)

    else:                               # M1-M3 路径（旧）
        # 直接迭代所有层，拼提示词
        return self._builder.build()
```

### 4.5 M2 事件钩子

当 Agent 读文件、写文件、切换目录时，Orchestrator 被通知并更新对应层：

```python
# loop.py 中：
if tool_name == "read_file":
    orchestrator.on_file_read(path, content)    # → WorkspaceLayer + FileCacheLayer
elif tool_name in ("edit_file", "write_file"):
    orchestrator.on_file_write(path)            # → WorkspaceLayer + 缓存失效
elif tool_name == "bash" and cmd.startswith("cd "):
    orchestrator.on_directory_changed(new_cwd)  # → WorkspaceLayer 更新
```

### 4.6 tick()：压缩检查入口

```python
def tick(self) -> bool:
    # 1. BudgetManager：检查所有层的 token 用量
    reports = self._budget_mgr.check(self.iter_layers())

    # 2. Policy：决策是否需要压缩
    plan = self._policy.evaluate(reports)
    if plan.action == "noop":
        return False   # 不需要压缩

    # 3. Pipeline：执行压缩（Tier1 → Tier2 → Tier3）
    result = self._pipeline.execute(ctx)
    return True
```

---

## 5. MCP Client：外部工具接入

**文件**：`src/bus/mcp_client.py`（约 340 行）

**背景**：MCP（Model Context Protocol）是 Anthropic 发布的开放协议，让 AI 可以调用外部工具服务器。比如 Brave Search 服务器让 Agent 能搜索网页。

### 5.1 协议流程

```
agent-core                      MCP Server (外部进程)
    │                                │
    │── 1. 启动子进程 ───────────────→│  node brave-search/dist/index.js
    │                                │
    │── 2. initialize ──────────────→│  协议握手，协商能力
    │←── capabilities ──────────────│
    │                                │
    │── 3. tools/list ──────────────→│  获取工具列表
    │←── [{"name":"search",...}] ───│
    │                                │
    │── 4. tools/call ──────────────→│  执行工具
    │←── {"content":[{...}]} ───────│
    │                                │
    │── 5. exit ────────────────────→│  关闭
```

### 5.2 核心实现

```python
class MCPServerConnection:
    """通过 stdio JSON-RPC 连接一个 MCP 服务器"""

    def start(self):
        # 1. 启动子进程
        self._process = subprocess.Popen(
            [self.command] + self.args,
            stdin=PIPE, stdout=PIPE, stderr=PIPE,
            env=env,  # 传递 API key 等
        )

        # 2. 初始化握手
        result = self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
        })

        # 3. 获取工具列表
        self._tools = self._request("tools/list", {})

    def call_tool(self, tool_name, arguments):
        """转发工具调用到 MCP 服务器"""
        return self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

    def _request(self, method, params):
        """发送 JSON-RPC 请求，等待响应"""
        with self._lock:
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            self._process.stdin.write(json.dumps(payload) + "\n")
            resp = self._process.stdout.readline()
            return json.loads(resp)["result"]
```

### 5.3 工具注册到 agent-core

```python
class MCPClientManager:
    def register_tools(self, registry):
        for server_name, server in self._servers.items():
            for tool_def in server.tool_definitions:
                # 工具名：mcp_<server>_<tool>
                agent_tool_name = f"mcp_{server_name}_{tool_name}"

                # 创建闭包处理器：调用时转发到 MCP 服务器
                def make_handler(srv, tname):
                    def handler(**kwargs):
                        return srv.call_tool(tname, kwargs)
                    return handler

                tool = build_tool(agent_tool_name, handler=make_handler(...))
                registry.register(tool)
```

### 5.4 配置文件格式

```json
// settings.json
{
  "mcp_servers": {
    "brave-search": {
      "command": "node",
      "args": ["brave-search/dist/index.js"],
      "env": {"BRAVE_API_KEY": "xxx"}
    }
  }
}
```

---

## 6. Intent Classification：意图路由

**文件**：`src/agent/intent.py`（约 190 行）

**问题**：每次都把所有 50 个工具发给 LLM → token 浪费 + 可能选错工具。

**解决**：先用 0 token 的正则匹配判断用户意图，只发相关工具。

### 6.1 七种意图

```python
DEFAULT_ROUTES = {
    "code_search":  ["grep", "glob", "memory_search", "read_file"],
    "code_edit":    ["read_file", "write_file", "edit_file", "bash"],
    "code_index":   ["memory_search", "grep", "glob", "read_file"],
    "task_manage":  ["task_create", "task_get", "task_update", "task_list",
                     "TodoWrite", "set_objective"],
    "web_search":   ["mcp_brave_search_*"],  # 动态填充
    "knowledge":    [],  # 不需要工具，直接回答
    "unsafe":       [],  # 直接拒绝，不发 LLM
}

# 任何意图下都有的工具
ALWAYS_AVAILABLE = ["list_skills", "load_skill", "compress",
                    "scratchpad_write", "scratchpad_read", "check_background"]
```

### 6.2 关键词匹配

```python
KEYWORD_PATTERNS = {
    "code_search": [
        r"\b(search|find|grep|look|搜索|查找|找)\b",
        r"\b(where|which).{0,30}\b(code|file|定义|实现)\b",
    ],
    "code_edit": [
        r"\b(edit|modify|change|fix|refactor|修改|改|修复|重构)\b",
        r"\b(run|execute|跑|执行).{0,15}\b(test|pytest|测试)\b",
    ],
    "unsafe": [
        r"\brm\s+-rf\s+/",     # 危险命令直接拦截
        r"\bsudo\s+rm\b",
    ],
}
```

### 6.3 在 loop.py 中的使用

```python
# 1. 找最后一条用户消息
last_user = ...
for msg in reversed(messages):
    if msg["role"] == "user":
        last_user = msg["content"]
        break

# 2. 分类意图
intent = classify_intent_fn(last_user)
# → "code_search"

# 3. 如果是 unsafe，直接拒绝
if intent == "unsafe":
    return  # 不发 LLM

# 4. 过滤工具
tools = filter_tools_fn(intent, all_tools)
# 从 50 个工具 → 6 个工具
```

---

## 7. Memory Core：记忆内核

**文件**：`src/memory/__init__.py` + 40+ 个子文件

**角色**：让 Agent 在不同会话之间记住知识。10 个子系统，每个只管一件事。

### 7.1 整体架构

```
                    ┌─────────────┐
                    │ MemoryCore  │  ← 唯一对外接口
                    └──────┬──────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      │                      │
    ▼                      ▼                      ▼
┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
│ Store  │  │Registry│  │ Schema │  │Identity│
│ CRUD   │  │ 类型注册│  │ 校验   │  │ ID体系 │
└────────┘  └────────┘  └────────┘  └────────┘
    │                      │                      │
    ▼                      ▼                      ▼
┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
│Metadata│  │ Index  │  │Pipeline│  │ Policy │
│ 扩展数据│  │ 索引   │  │ 5阶段  │  │ 7规则  │
└────────┘  └────────┘  └────────┘  └────────┘
    │                      │                      │
    ▼                      ▼                      ▼
┌────────┐  ┌────────┐
│Lifecycle│ │EventBus│
│ 状态机  │ │ 发布订阅│
└────────┘  └────────┘
```

### 7.2 一条记忆的生命周期

```
用户: memory_add(type="knowledge", content="用 pytest 做测试")

    ↓
① SchemaLayer    → 校验字段是否合法
    ↓
② NormalizeStage → 标准化（去多余空格、统一标签格式）
    ↓
③ DeduplicateStage → 去重（和已有记忆比较，相似度 > 80% 则合并）
    ↓
④ PolicyCheckStage → 策略检查（长度、禁止词、类型限制...）
    ↓
⑤ PersistStage   → 写入 Store + 更新索引 + 触发事件 + 保存到磁盘
    ↓
    ✓ memory.json
```

### 7.3 MemoryCore 用法

```python
# main.py 中：
core = MemoryCore(db_path=Path(".memory"))
core.load()                           # 从磁盘恢复

# 初始化 M7-M10（按依赖顺序）
retrieval    = core.init_retrieval()    # 语义搜索
importance   = core.init_importance()   # 动态打分 + 衰减
intelligence = core.init_intelligence(llm_call=...)  # 自动提取 + 反思
lifecycle    = core.init_lifecycle(llm_call=...)     # 归档 + 压缩 + GC

# 注册 Agent 可调用的工具
tools = build_memory_tools(core.store, core.pipeline, retrieval_engine)
registry.register_many(tools)
```

### 7.4 10 个子系统速览

| # | 子系统 | 一句话 | 关键文件 |
|---|--------|--------|----------|
| 1 | Store | 纯 CRUD + 3 池(active/archived/deleted) + 持久化 | `store.py` |
| 2 | Registry | 注册内置/自定义记忆类型，支持插件 | `registry.py` |
| 3 | Schema | 校验每个 entry 的字段完整性 | `schema.py` |
| 4 | Identity | MemoryID, SessionID, ProjectID 等强类型 ID | `identity.py` |
| 5 | Metadata | 解耦的键值扩展数据（不污染主模型） | `metadata.py` |
| 6 | Index | 5 种索引（type/tag/project/owner/state） | `index.py` |
| 7 | Pipeline | 入站 5 阶段处理（Schema→Normalize→Dedup→Policy→Persist） | `pipeline.py` |
| 8 | Policy | 7 条规则（长度/禁止词/去重/类型限制/来源限制...） | `policy.py` |
| 9 | Lifecycle | 5 状态状态机（active→warm→cold→archived→deleted） | `lifecycle/` |
| 10 | EventBus | 发布/订阅，解耦子系统间通信 | `events.py` |

---

## 8. Memory 检索 (M7)：三通道混合搜索

**文件**：`src/memory/retrieval/`

### 8.1 三通道架构

```
用户查询 "how to test"
        │
        ▼
┌───────────────────────────────────┐
│         MemoryPlanner             │
│   分析查询 → RetrievalIntent      │
│   {type: "hybrid", target: ...}   │
└───────────┬───────────────────────┘
            │
    ┌───────┼───────┐
    ▼       ▼       ▼
┌──────┐ ┌──────┐ ┌──────┐
│Vector│ │Keyword│ │Recent│
│语义  │ │关键词│ │最近  │
└──┬───┘ └──┬───┘ └──┬───┘
   │        │        │
   ▼        ▼        ▼
┌─────────────────────────┐
│    HybridFusion          │
│  RRF 或 WeightedSum     │
│  融合三路结果            │
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│      Reranker            │
│  综合重要性、新鲜度、    │
│  频率重新排序            │
└───────────┬─────────────┘
            ▼
       最终结果列表
```

### 8.2 向量化的异步模式

```python
class EmbeddingIndex:
    def add(self, entry_id, text):
        # 立即加入"待处理"队列，不阻塞
        self._pending_queue.put((entry_id, text))

class EmbeddingWorker(threading.Thread):
    def run(self):
        while self._running:
            entry_id, text = self._pending_queue.get()
            # 后台线程生成 embedding
            vector = self._encoder.encode(text)
            self._vector_index.add(entry_id, vector)
```

### 8.3 融合算法

```python
# Reciprocal Rank Fusion (RRF)
def rrf_score(rank, k=60):
    return 1.0 / (k + rank)

final_score = rrf_score(vector_rank) + rrf_score(keyword_rank) + rrf_score(recent_rank)

# Weighted Sum Fusion
final_score = (0.5 * vector_score + 0.3 * keyword_score + 0.2 * recent_score)
```

---

## 9. 压缩管线 (M3)：三级压缩 + 熔断

**文件**：`src/context/compression/`

### 9.1 三部曲

```
tick() 调用流程：

① BudgetManager.check(layers)
   → 扫描所有层，计算当前 token 用量
   → 返回 BudgetReport（哪些层超预算了）

② CompressionPolicy.evaluate(reports)
   → 看规则（如："conversation 层连续 2 次超预算 10%，触发压缩"）
   → 返回 CompressionPlan（action: compress/noop, tier: 1/2/3）

③ CompressionPipeline.execute(ctx)
   → 按 plan 执行对应阶段：
     Tier 1: MicroCompact — 清旧工具结果，保留最近 3 个
     Tier 2: ContextCollapse — 分组对话，中间轮次 LLM 摘要
     Tier 3: AutoCompact — 全对话 LLM 总结（兜底）
```

### 9.2 熔断器

```python
class CircuitBreaker:
    """连续 3 次 LLM 调用失败 → 熔断 60 秒，期间只做 Tier 1"""
    def record_failure(self):
        self.failures += 1
        if self.failures >= self.max_failures:
            self.is_open = True
            self.opened_at = time.time()

    def record_success(self):
        self.failures = 0
        self.is_open = False
```

---

## 10. Context Selection (M4)：上下文选择

**文件**：`src/context/selection/`

### 10.1 四步流水线

```
Collect → Rank → Select → Pack

① Collectors：从各层收集内容
   InstructionCollector  → 系统指令
   WorkspaceCollector    → 工作区信息
   MemoryCollector       → 记忆搜索结果
   SummaryCollector      → 压缩摘要
   FileCacheCollector    → 文件缓存
   ConversationCollector → 对话历史

② Rankers：排优先级
   PriorityRanker → 按 source 的重要程度排序

③ Policy：按 token 预算砍掉低优先级的
   TokenConstraint(source="instruction", max_tokens=10%, reserved=True)
   TokenConstraint(source="conversation", max_tokens=60%, reserved=False)
   ...

④ Packer：把选中的打包成 PromptPackage
```

### 10.2 为什么需要这个？

**问题**：当上下文窗口只有 100K token 时，60K 给对话历史，10K 给系统指令，剩下 30K 怎么分配给 workspace、file_cache、memory、summary？

**解决**：Collect→Rank→Select→Pack 自动决策。优先保留 reserved=True 的内容（指令、工作区），其余按优先级竞争剩余 budget。

---

## 11. Eval 评估系统

**文件**：`src/eval/` + `run_bfcl.py` + `run_gaia.py` + `run_context_fidelity.py`

### 11.1 三种评测

| 评测 | 测什么 | 入口 |
|------|--------|------|
| BFCL | 工具调用准确率（函数选择+参数填充） | `run_bfcl.py` |
| GAIA | 多步推理能力（需要搜索+工具组合） | `run_gaia.py` |
| Context Fidelity | 上下文保真度（长对话中信息是否丢失） | `run_context_fidelity.py` |

### 11.2 BFCL 评测流程

```python
# src/eval/bfcl_loader.py
class BFCLLoader:
    def load(self, data_dir):
        # 加载 BFCL 数据集（JSON 格式）
        # 每个 case: {user_query, expected_tool, expected_args}
        ...

# src/eval/runner.py
class EvalRunner:
    def run_bfcl(self, cases, agent_fn):
        for case in cases:
            _, tool_calls = agent_fn(case.query)
            score = self._score(case.expected, tool_calls)
        return aggregate_scores
```

### 11.3 Context Fidelity 评测

测试长对话中 Agent 是否"忘记"信息：
1. 在对话开头注入一个事实（如 "API key 是 abc123"）
2. 经过 50 轮对话（触发多次压缩）
3. 问 Agent "API key 是什么？"
4. 检查是否还能正确回答

---

## 12. 整体架构回顾

### 12.1 数据流全景

```
main.py (装配)
  │
  ├── Anthropic Client  ← DeepSeek V4-Pro
  ├── MCPClientManager  ← 外部工具服务器
  ├── IntentClassifier  ← 7 种意图路由
  ├── MemoryCore        ← 10 子系统记忆内核
  └── ContextOrchestrator ← 上下文总调度
        │
        └──→ agent_loop() (执行)
              │
              ├── ① tick()          → 压缩检查
              ├── ② build_prompt()  → 组装上下文
              ├── ③ classify()      → 意图分类
              ├── ④ LLM call        → API 调用
              ├── ⑤ execute tools   → 工具执行
              └── ⑥ 回到 ①
```

### 12.2 核心设计模式

| 模式 | 在哪 | 为什么 |
|------|------|--------|
| **Facade** | Orchestrator, MemoryCore | 隐藏内部复杂性，外部只接触一个对象 |
| **Layer Registry** | Orchestrator._layers | 新加功能不改现有代码 |
| **Pipeline** | Memory Pipeline, Compression Pipeline, Selection Pipeline | 把流程拆成独立阶段，可组合可替换 |
| **Lazy Init** | M7-M10 engines | 按需初始化，不用的不启动 |
| **Circuit Breaker** | Compression | 防止 LLM 连续失败时无限重试 |
| **Closure Factory** | MCP tool handler | 用闭包捕获 server + tool_name，避免 late binding 问题 |
| **Strategy Pattern** | IntentClassifier (keyword vs llm) | 同接口多实现，按配置切换 |

### 12.3 各模块依赖关系

```
                    ┌─────────────┐
                    │   main.py   │  装配一切
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ loop.py  │ │ memory/  │ │ context/ │
        │ 主循环   │ │ 记忆内核 │ │ 上下文   │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │            │            │
    ┌────────┼─────┐      │     ┌──────┼──────┐
    ▼        ▼     ▼      │     ▼      ▼      ▼
┌──────┐ ┌────┐ ┌────┐   │  ┌────┐ ┌────┐ ┌────┐
│hooks │ │int │ │filt│   │  │lay │ │comp│ │sel │
│      │ │ent │ │er  │   │  │ers │ │ress│ │ect │
└──────┘ └────┘ └────┘   │  └────┘ └────┘ └────┘
                          │
                    ┌─────┴─────┐
                    ▼           ▼
              ┌──────────┐ ┌──────────┐
              │retrieval │ │lifecycle │
              │检索 (M7) │ │生命周期  │
              └──────────┘ └──────────┘
```

### 12.4 建议的深入阅读顺序

如果你想把每个子系统彻底搞懂：

1. **Store + Pipeline**（`memory/store.py` + `memory/pipeline.py`）— 最基础，理解一条数据怎么存、怎么过流水线
2. **Compression Pipeline**（`context/compression/pipeline.py`）— 看三个 Stage 怎么接力
3. **Selection Pipeline**（`context/selection/pipeline.py`）— 看 Collect→Rank→Select→Pack 怎么决策
4. **Retrieval Pipeline**（`memory/retrieval/pipeline.py`）— 看三通道混合搜索怎么融合
5. **Hook 系统**（`src/agent/hooks.py`）— 看五个生命周期事件怎么拦截
6. **Intelligence Engine**（`memory/intelligence/engine.py`）— 看自动提取 + 反思策略怎么工作
7. **Lifecycle Engine**（`memory/lifecycle/engine.py`）— 看 5 状态机 + GC 怎么维护记忆健康

---

*文档生成于 2026-07-05，基于 agent-core 当前代码版本*
