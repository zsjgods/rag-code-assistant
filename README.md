# agent-core v2.0

**逐模块实现 Claude Code 核心架构的教学级 Agent 框架。**

不是 LangChain 替代品。是你可以逐文件阅读、逐模块理解的 Agent 底层原理参考实现。

从 ReAct 循环、钩子系统、三层压缩到完整记忆系统和评测体系——每个模块对应 Claude Code 的一个实际能力，代码量可控、依赖极少。

## 目录结构

```
agent-core/
├── main.py                     # 主入口：初始化所有模块 + REPL
├── settings.json               # 配置：Hook、Agent、MCP、意图路由
├── pyproject.toml              # 项目元数据（v2.0.0）
│
├── src/
│   ├── agent/                  # Agent 核心
│   │   ├── loop.py             #   ReAct 主循环（Reason → Action）
│   │   ├── hooks.py            #   5 事件钩子系统（SessionStart → Stop）
│   │   ├── intent.py           #   意图分类（keyword/LLM 模式）
│   │   └── filter_tools.py     #   子 Agent 三层工具隔离
│   │
│   ├── context/                # Context Engine（M1-M5）
│   │   ├── orchestrator.py     #   统一入口 + 层注册
│   │   ├── prompt_builder.py   #   分层 prompt 组装
│   │   ├── layers/             #   6 个上下文层
│   │   ├── budget/             #   Token 预算管理
│   │   ├── compression/        #   三级压缩管线 + 熔断器
│   │   ├── selection/          #   M4 上下文选择管线
│   │   ├── serialization/      #   M5 序列化
│   │   ├── recovery/           #   M5 状态恢复
│   │   ├── replay/             #   M5 历史重放
│   │   └── observability/      #   M5 可观测性
│   │
│   ├── memory/                 # Memory OS（M6-M10）
│   │   ├── store.py            #   三层池 CRUD + JSON 持久化
│   │   ├── pipeline.py         #   写入管线（5 阶段）
│   │   ├── tools.py            #   7 个 Agent 可用记忆工具
│   │   ├── layer.py            #   Context OS 适配层
│   │   ├── retrieval/          #   M7 混合检索（Keyword + Vector + Recent）
│   │   ├── importance/         #   M8 重要性引擎（打分 + 衰减 + 追踪）
│   │   ├── intelligence/       #   M9 智能层（LLM 自动提取 + 冲突检测）
│   │   └── lifecycle/          #   M10 生命周期管理（归档 + GC）
│   │
│   ├── compression/            # 基础压缩工具
│   │   ├── micro.py            #   零成本清理旧工具结果
│   │   ├── collapse.py         #   重要性评分 + 分组摘要
│   │   └── auto.py             #   全对话 LLM 总结
│   │
│   ├── tools/                  # 工具系统
│   │   ├── base.py             #   Tool 接口定义
│   │   ├── registry.py         #   工具注册中心
│   │   └── builtin/            #   bash / read / write / edit / grep / glob
│   │
│   ├── eval/                   # 评测体系
│   │   ├── runner.py           #   BFCL 评测框架（AST 匹配）
│   │   ├── context_fidelity.py #   上下文保真度评测（5 场景）
│   │   ├── test_cases.py       #   30 个工具调用测试用例
│   │   ├── bfcl_loader.py      #   BFCL v3 数据加载
│   │   └── gaia_loader.py      #   GAIA 数据加载
│   │
│   ├── recovery/               # 容错
│   ├── bus/                    # 通信（MessageBus + Scratchpad + MCP）
│   ├── tasks/                  # 任务管理
│   ├── skills/                 # SKILL.md 加载
│   ├── state/                  # Observable Store
│   └── config/                 # 分层配置合并
│
├── scripts/                    # 评测 & 验证入口
│   ├── run_eval.py
│   ├── run_bfcl.py
│   ├── run_gaia.py
│   ├── run_context_fidelity.py
│   ├── verify_m8.py
│   ├── verify_m9.py
│   └── verify_m10.py
│
├── eval_data/                  # 评测数据（不跟踪 git）
├── examples/hooks-demo/        # 钩子系统示例
├── tests/                      # 测试
```

## 核心架构

### Agent 主循环（ReAct）

完整的"推理 → 行动 → 观察"循环，每轮集成 Hook、压缩、意图分类和工具过滤：

```
User Input
  → Hook: UserPromptSubmit（注入上下文）
  → Intent Classification（安全 → 工具路由）
  → Context Assembly（分层组装 prompt）
  → LLM Reasoning
  → Tool Execution（PreToolUse hook → 执行 → PostToolUse hook）
  → Budget Check（超阈值 → 三级压缩）
  → 循环直到 stop_reason != tool_use
```

### 三层上下文压缩

| 层级 | 名称 | 成本 | 产物 |
|---|---|---|---|
| Tier 1 | MicroCompact | 0 token | 清理旧 tool_result → `[cleared]` |
| Tier 2 | ContextCollapse | N 次 LLM 调用 | 中间轮次重要性评分摘要 → `[collapsed]` |
| Tier 3 | AutoCompact | 1 次 LLM 调用 | 全对话总结 → `<summary>` |

压缩时检测到关键事件（`goal_declaration` / `error_fix` / `decision_made`）自动提取到 Store，注入 system prompt 的 `<persistent-context>` 块，不再参与后续压缩。

### 记忆系统（Memory OS）

三级存储：

```
工作记忆（Store → 进程内存）
  ├── 当前目标 + 关键决策点
  └── 注入 system prompt，不参与压缩
  
会话记忆（ConversationLayer + SummaryLayer）
  ├── 本轮对话历史
  └── Tier 3 压缩后的摘要
  
长期记忆（MemoryStore → JSON）
  ├── 跨会话持久化
  └── 混合检索：Keyword + Vector + Recent
```

十个子系统（M6-M10）：Store → Pipeline → Policy → Index → Retrieval → Importance → Intelligence → Lifecycle → GC → Events。

### 钩子系统

5 个生命周期事件：SessionStart → UserPromptSubmit → PreToolUse → PostToolUse → Stop。

每种事件支持 **Command**（Shell 脚本）和 **Prompt**（调 LLM 判断）两种执行引擎。返回 JSON 协议：`decision`（approve/block）、`updatedInput`（修改参数）、`additionalContext`（注入内容）。

### 三层工具隔离

1. **全局禁止列表**：Agent、TaskStop、AskUserQuestion 等防递归
2. **类型白名单**：Explore（只读）/ background（受限）/ general-purpose（全部）
3. **Agent 自定义**：allowedTools / disallowedTools 最终裁决

## 安装

```bash
# 克隆
git clone https://github.com/zsjgods/rag-code-assistant.git
cd rag-code-assistant

# 安装依赖
pip install anthropic python-dotenv

# 创建 .env（不要提交到 git）
echo 'ANTHROPIC_API_KEY=your-key' > .env
echo 'MODEL_ID=claude-sonnet-4-6-20250514' >> .env

# 启动
python main.py
```

## REPL 命令

| 命令 | 作用 |
|------|------|
| `/compact` | 手动触发上下文压缩 |
| `/tasks` | 查看任务看板 |
| `/hooks` | 查看钩子统计 |
| `/skills` | 列出已加载技能 |
| `/memory` | 查看记忆状态 |

## 评测

| 评测 | 用例数 | 测什么 |
|---|---|---|
| BFCL v3 | ~1240 | 工具选择准确性（AST 匹配） |
| Context Fidelity | 5 场景 | 压缩后目标/约束/决策是否保持 |
| GAIA | 466 | 端到端多步推理 |
| 内置用例 | 30 | 工具选择 + 无关场景抑制 + 多轮 + 并行 |

## 设计目标

- **可理解**：每个模块不超过几百行，关键路径有注释
- **可运行**：依赖极少（anthropic + python-dotenv），开箱即用
- **可修改**：LRU 缓存、压缩参数、Hook 策略均可配置
- **可测试**：M8/M9/M10 独立验证脚本 + BFCL/GAIA/保真度评测

## License

MIT
