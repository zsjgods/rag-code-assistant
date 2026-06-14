# agent-core

**逐模块实现 Claude Code 核心架构的教学级 Agent 框架。**

不是 LangChain 替代品。是可以逐文件阅读、逐模块理解的 Agent 底层原理参考实现。

从 learn-claude-code 的 s01-s11 生长而来，重构后加入钩子系统、三级压缩、工具隔离、技能加载。

## 目录结构

```
agent-core/
├── main.py                     # 主入口 + REPL
├── settings.json               # 默认配置
│
├── src/
│   ├── agent/
│   │   ├── loop.py             # Agent 主循环（含钩子插入点）
│   │   ├── hooks.py            # 钩子系统（5 个生命周期事件）
│   │   └── filter_tools.py     # 子 Agent 工具隔离（三层过滤）
│   │
│   ├── compression/
│   │   ├── micro.py            # Micro-compact：零成本清理旧工具结果
│   │   ├── collapse.py         # Context collapse：按 API 往返分组摘要
│   │   └── auto.py             # Auto-compact：全对话 LLM 总结
│   │
│   ├── tools/
│   │   ├── base.py             # Tool 接口（含安全标志位）
│   │   ├── registry.py         # 工具注册中心
│   │   └── builtin/            # bash / read / write / edit / grep / glob
│   │
│   ├── skills/
│   │   └── loader.py           # SKILL.md 解析 + 参数替换
│   │
│   ├── state/
│   │   └── store.py            # Observable Store + 子 Agent 状态隔离
│   │
│   ├── bus/
│   │   ├── message_bus.py      # JSONL 消息总线
│   │   └── scratchpad.py       # 免权限跨 Agent 共享空间
│   │
│   ├── tasks/
│   │   ├── todo.py             # 内存待办管理
│   │   └── task_manager.py     # 文件持久化任务看板
│   │
│   ├── config/
│   │   └── loader.py           # 分层配置合并
│   │
│   └── recovery/
│       ├── error_handler.py    # 分级重试 + 指数退避
│       └── session.py          # 会话持久化（bridgePointer）
│
├── examples/hooks-demo/        # 钩子示例（危险命令拦截/审计/完整性检查）
└── tests/test_hooks.py         # 钩子系统测试
```

## 核心功能

### 钩子系统

5 个生命周期事件：SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop。

支持两种执行引擎：Command（Shell 脚本）和 Prompt（调 LLM 判断）。

JSON 响应协议：`decision`（approve/block）、`updatedInput`（修改工具参数）、`additionalContext`（注入上下文）。

退出码语义：0 = 放行，2 = 阻止并展示 stderr 给模型，其他非 0 = 警告但继续。

优先级排序：local > project > user，任意钩子 block 则操作被阻止。

### 三级压缩

1. **Micro-compact**：清理旧工具结果，保留最近 N 个，零 token 成本
2. **Context collapse**：按 API 往返分组，中段每组单独摘要，成本可控
3. **Auto-compact**：调 LLM 全对话总结，最后手段兜底

熔断器：连续 3 次压缩失败 → 停止尝试，防止烧 token。

### 工具隔离

三层过滤保障子 Agent 安全：

1. **全局禁止列表**：Agent、TaskStop、AskUserQuestion 等，防递归和越权
2. **类型白名单**：Explore（只读）、background（受限集）、general-purpose（全部）
3. **Agent 自定义**：allowedTools / disallowedTools 最终裁决

### 技能系统

Markdown frontmatter 声明式定义，支持参数替换：`$ARGUMENTS`、`$1`、`$method`、`${CLAUDE_SKILL_DIR}`。

条件激活：`paths` 字段匹配文件模式时自动触发，一旦激活永久标记。

### Scratchpad 共享空间

物理路径：`/tmp/s_full_<id>/scratchpad/`。免权限检查，跨 Agent 读写。

Agent A 写入分析 → Agent B 读取 → Coordinator 消化综合。

## 快速开始

```bash
# 克隆
git clone https://github.com/zsjgods/rag-code-assistant.git
cd rag-code-assistant

# 安装依赖
pip install anthropic python-dotenv

# 设置 API Key
export ANTHROPIC_API_KEY=your-key
export MODEL_ID=claude-sonnet-4-6-20250514

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

## 钩子配置示例

编辑 `settings.json`：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 examples/hooks-demo/check_dangerous.py",
            "timeout": 3000
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"additionalContext\": \"Git: '$(git branch --show-current 2>/dev/null)'\"}'",
            "timeout": 2000
          }
        ]
      }
    ]
  }
}
```

## 架构文档

详见 [ARCHITECTURE.md](ARCHITECTURE.md) — 设计决策、模块对照、与 Claude Code 的架构对比。

## License

MIT
