# agent-core

**逐模块实现 Claude Code 核心架构的教学级 Agent 框架。**

不是 LangChain 替代品。是可以逐文件阅读、逐模块理解的 Agent 底层原理参考实现。

## 目录结构

```
agent-core/
├── main.py                     # 主入口 + REPL
├── settings.json               # 默认配置 + Hook 定义 + Agent 路由
│
├── src/
│   ├── agent/
│   │   ├── loop.py             # Agent 主循环（ReAct：Reason + Action）
│   │   ├── hooks.py            # 钩子系统（5 个生命周期事件）
│   │   ├── intent.py           # 意图分类（keyword / llm 模式）
│   │   └── filter_tools.py     # 子 Agent 工具隔离（三层过滤）
│   │
│   ├── context/                # Context Engine — 分层上下文管理
│   │   ├── orchestrator.py     # 统一入口（Layer 注册 + Prompt 组装）
│   │   ├── prompt_builder.py   # 分层 prompt 组装器
│   │   ├── layers/             # 各上下文层
│   │   ├── compression/        # 三级压缩管线 + 熔断器
│   │   ├── budget/             # Token 预算管理
│   │   ├── selection/          # M4 上下文选择管线
│   │   └── types.py
│   │
│   ├── memory/                 # Memory OS — 记忆系统
│   │   ├── store.py            # 三层池存储（active/archived/deleted）
│   │   ├── pipeline.py         # 写入管线（5 阶段）
│   │   ├── types.py            # MemoryEntry、MemoryType
│   │   ├── tools.py            # Agent 可调用的记忆工具集
│   │   ├── layer.py            # Context OS 适配层
│   │   ├── retrieval/          # M7 混合检索
│   │   ├── importance/         # M8 重要性引擎
│   │   ├── intelligence/       # M9 智能层（LLM 自动提取）
│   │   └── lifecycle/          # M10 生命周期管理
│   │
│   ├── compression/
│   │   ├── micro.py            # 零成本清理旧工具结果
│   │   ├── collapse.py         # 重要性评分 + 分组摘要
│   │   └── auto.py             # 全对话 LLM 总结
│   │
│   ├── tools/
│   │   ├── base.py             # Tool 接口
│   │   ├── registry.py         # 工具注册中心
│   │   └── builtin/            # bash / read / write / edit / grep / glob
│   │
│   ├── eval/                   # 评测体系
│   │   ├── runner.py           # BFCL 评测框架
│   │   ├── context_fidelity.py # 上下文保真度评测
│   │   ├── test_cases.py       # 30 个工具调用测试用例
│   │   ├── bfcl_loader.py      # BFCL v3 数据加载
│   │   └── gaia_loader.py      # GAIA 数据加载
│   │
│   ├── recovery/
│   │   ├── error_handler.py    # 分级重试 + 指数退避
│   │   └── session.py          # 会话持久化
│   │
│   ├── bus/
│   │   ├── message_bus.py      # JSONL 消息总线
│   │   ├── scratchpad.py       # 跨 Agent 共享空间
│   │   └── mcp_client.py       # MCP 服务器发现 + 动态工具注册
│   │
│   ├── tasks/
│   │   ├── todo.py             # 内存待办管理
│   │   └── task_manager.py     # 文件持久化任务看板
│   │
│   ├── skills/
│   │   └── loader.py           # SKILL.md 解析 + 参数替换
│   │
│   ├── state/
│   │   └── store.py            # Observable Store + 子 Agent 状态隔离
│   │
│   └── config/
│       └── loader.py           # 分层配置合并
│
├── examples/hooks-demo/        # 钩子示例（危险命令拦截/审计）
├── run_eval.py                 # BFCL 工具评测入口
├── run_context_fidelity.py     # 上下文保真度评测入口
├── run_gaia.py                 # GAIA 评测入口
├── run_bfcl.py                 # BFCL v3 评测入口
├── verify_m8.py                # M8 重要性引擎验证
├── verify_m9.py                # M9 智能层验证
└── verify_m10.py               # M10 生命周期验证
```

## 核心功能

### 三层上下文压缩

1. **Micro-compact**：清理旧工具结果，保留最近 N 个，零 token 成本
2. **Context collapse**：按重要性评分分组摘要，`goal_declaration` / `error_fix` / `decision_made` 写入 Store（压缩免疫）
3. **Auto-compact**：全对话 LLM 总结 → 写入 SummaryLayer

熔断器：连续 3 次压缩失败 → 停止尝试，防止烧 token。

### 记忆系统（Memory OS）

十个子系统，三级存储：
- **工作记忆**（Store）：当前目标和关键决策点，注入 system prompt
- **会话记忆**（ConversationLayer + SummaryLayer）：对话历史 + 压缩摘要
- **长期记忆**（MemoryStore / JSON）：跨会话持久化，支持关键词 + 语义 + 最近三条混合检索

### 钩子系统

5 个生命周期事件：SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop。
支持两种执行引擎：Command（Shell 脚本）和 Prompt（调 LLM 判断）。
优先级排序：local > project > user，任意钩子 block 则操作被阻止。

### 评测体系

| 评测 | 覆盖范围 | 方法 |
|---|---|---|
| **BFCL** | 30 用例：simple / irrelevant / multiple / parallel | AST 匹配 + 参数校验 |
| **Context Fidelity** | 5 场景：目标保持 / 约束保持 / 决策回溯 / 多目标 / Scratchpad | 干扰 → 压缩 → LLM Judge 评分 |
| **GAIA** | 真实世界多步推理 | 端到端任务完成度 |

### 工具隔离

三层过滤保障子 Agent 安全：
1. 全局禁止列表：Agent、TaskStop、AskUserQuestion 等
2. 类型白名单：Explore（只读）、background（受限集）、general-purpose（全部）
3. Agent 自定义：allowedTools / disallowedTools 最终裁决

## 快速开始

```bash
# 克隆
git clone https://github.com/zsjgods/rag-code-assistant.git
cd rag-code-assistant

# 安装依赖
pip install anthropic python-dotenv

# 创建 .env 文件（不要提交到 git）
echo 'ANTHROPIC_API_KEY=your-key' > .env
echo 'MODEL_ID=claude-sonnet-4-6-20250514' >> .env

# 运行
python main.py
```

## REPL 命令

| 命令 | 作用 |
|------|------|
| `/compact` | 手动触发压缩 |
| `/tasks` | 查看任务看板 |
| `/hooks` | 查看钩子统计 |
| `/skills` | 列出已加载技能 |
| `/memory` | 查看记忆状态 |

## License

MIT
