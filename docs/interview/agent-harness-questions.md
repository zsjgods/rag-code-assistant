# Agent Harness 面试题整理

> 围绕多轮 Agent 系统中的上下文治理、压缩、记忆、校验等核心问题。
> 每个问题包含：问题原文 → 回答参考 → 追问/深度分析 → 代码对照

---

## 目录

1. [多轮任务中的上下文治理（真实场景）](#1-多轮任务中的上下文治理真实场景)
2. [压缩后如何判断没有破坏当前任务](#2-压缩后如何判断没有破坏当前任务)
3. [Store 的角色和工作原理](#3-store-的角色和工作原理)
4. [三层压缩产物各存在哪、怎么维护](#4-三层压缩产物各存在哪怎么维护)
5. [只压缩对话层，其他层满了怎么办](#5-只压缩对话层其他层满了怎么办)
6. [上下文压缩的分段策略](#6-上下文压缩的分段策略)
7. [压缩后关键约束遗漏，如何发现和修正](#7-压缩后关键约束遗漏如何发现和修正)
8. [长期记忆过时污染怎么处理](#8-长期记忆过时污染怎么处理)
9. [多轮执行中反复读文件/调工具，怎么识别重复状态](#9-多轮执行中反复读文件调工具怎么识别重复状态)
10. [什么是 Agent Harness？和单纯调 LLM API 的区别](#10-什么是-agent-harness和单纯调-llm-api-的区别)
11. [Context Engineering / Prompt Engineering / Harness Engineering 区别](#11-context-engineering--prompt-engineering--harness-engineering-区别)
12. [ReAct 范式讲解](#12-react-范式讲解)
13. [Agent 工作流范式：ReAct、Plan-and-Execute、Memory-augmented 对比](#13-agent-工作流范式对比)
14. [过时记忆的版本化处理](#14-过时记忆的版本化处理)

---

## 1. 多轮任务中的上下文治理（真实场景）

### 问题

你提到做了多轮任务中的上下文治理，可以举一个真实场景吗？比如代码改到一半上下文越来越长，你是怎么处理的？

### 回答参考

假设 15 轮对话后 messages 累积到 12 万 token，系统通过**三级渐进压缩**处理：

**Tier 1 — MicroCompact（零成本清理）：** 扫描所有 tool_result，将 3 轮之前的超大返回体（读文件内容、git diff 输出）直接设成 `[cleared]`，不调 LLM，约从 12 万降到 9 万 token。

**Tier 2 — ContextCollapse（LLM 压缩中间轮次）：** 按 API round-trip 分组，保留 head=3 + tail=3 组原文，中间的组喂给 LLM 做 importance-scored summarization。LLM 返回 JSON 包含 summary、importance、key_facts。

**重要性分级：**
- `goal_declaration` → 写入 Store（永不丢失）
- `error_fix` → 写入 Store
- `decision_made` → 写入 Store
- `intermediate_step` → 正常压缩
- `chitchat` → 激进压缩

**结果：** 12 万 → 约 4 万 token，且关键决策点被搬到了 system prompt 的 `<persistent-context>` 块，后续不再参与压缩。

### 追问：工具返回是 user 角色？assistant 到 assistant 分段会不会太频繁？

**回答：** 对，tool_result 必须是 user 角色（Anthropic Messages API 规定）。当前的 `_group_by_roundtrip()` 按 assistant 边界分组确实过于碎片化，多工具回合被切成多个小 group 全部跳过压缩。

### 追问：那怎么改进分段？

**回答：** 改进方案是按**用户消息边界**分组 + 最大尺寸兜底：
- 纯文本 user 消息（`isinstance(content, str)`）→ 新意图，切分
- 含 tool_result 的 user 消息 → 接续当前组
- 当前组超过 30000 字符 → 强制切分

不需要语义理解来识别意图——纯文本和 tool_result 在 API 格式上天然可区分，100% 准确。切偏了也没关系，压缩后的 `[collapsed]` 摘要本身在对话层里，新组能看到前一组的概要。

---

## 2. 压缩后如何判断没有破坏当前任务

### 问题

上下文压缩之后，你怎么判断压缩没有破坏当前任务？有没有什么校验标准？

### 回答参考

我会做三个校验：

**第一是目标一致性校验：** 压缩后的摘要必须保留用户原始目标、硬约束和验收标准。通过 Store 的 `<persistent-context>` 实现——压缩时检测到 `goal_declaration` / `error_fix` / `decision_made` 级别的轮次，将其 key_facts 持久化到 Store，每次 LLM 调用前注入 system prompt。

**第二是状态完整性校验：** 必须包含已读文件、已改文件、测试结果、失败尝试和下一步计划。这部分当前没有完整覆盖——FileCacheLayer 和 WorkspaceLayer 独立于压缩流程，压缩不校验它们是否仍在。

**第三是引用校验：** 对关键代码事实，尽量保留文件路径、函数名、行号或符号名，而不是只写自然语言总结。当前 `SCORING_PROMPT` 没有要求 LLM 保留符号引用，这是缺陷。

**行为偏离检测（最实用的零成本校验）：** 不需要专门的验证步骤，而是在 Agent 执行关键操作（`edit_file`/`write_file`）前快速自查目标是否偏离。这比专门的压缩后验证成本低得多，且能覆盖校验规则写不出来的边界情况。

### 追问：如果行为偏离检测没触发，但 Agent 已经基于错误信息写了一堆代码，怎么修复？

**回答：** 回退策略要看改动规模。小改动可以逆操作，大改动则告诉用户并让用户决定。关键是不能盲目信任摘要——`messages[:] = collapsed` 是单向的，原始消息不可恢复。实际可行的做法是：重新读关键文件（文件在磁盘上）、从 Store 重新确认目标（Store 里的没丢）、修正后让 LLM 重新规划再执行。

---

## 3. Store 的角色和工作原理

### 问题

Store 是一个对象吗？怎么存的？

### 回答参考

`Store` 就是一个进程内共享的 `dict`，全名"运行时状态暂存区"或"工作记忆"：

```python
class Store:
    def __init__(self, initial: dict | None = None):
        self._state: dict = initial or {}
        self._listeners: list = []
    def get(self, key, default=None): ...
    def set(self, key, value): ...
```

**没有持久化到磁盘。** 进程结束就丢。它在 `main.py` 中以全局单例存在：`STORE = Store({"cwd": str(WORKDIR), "model": MODEL})`

**存什么：** `current_objective`（当前目标）、`persistent_facts`（关键决策点列表，最多 10 条）、`cwd`、`model`。

**写入路径：** ContextCollapseStage 压缩时 → `on_important()` → `STORE.set("persistent_facts", [...])`

**读取路径：** 每次 LLM 调用前 → `InstructionLayer.render()` 通过回调读 Store → 渲染 `<persistent-context>` 注入 system prompt。

### 追问：Store 就是工作记忆？只记录当前目标？各层不从 Store 中读取？

**回答：** 对。Store 只存"不能丢的几件关键事"，不存执行痕迹。各层（ConversationLayer、SummaryLayer、WorkspaceLayer、FileCacheLayer）都有自己的状态，不从 Store 读取。唯一通过 Store 的是 `InstructionLayer` 的 `<persistent-context>` 块。`PromptBuilder.build()` 遍历各层挨个调 `render()`，每层自管自产出内容，拼成最终传给 API 的 (system + messages)。

---

## 4. 三层压缩产物各存在哪、怎么维护

### 问题

任务摘要、文件摘要、过程笔记这些压缩产物，你是怎么生成和维护的？如何避免关键信息被压掉？全部写进 Store 保存吗？只压缩对话层是吗？

### 回答参考

**不是全部写进 Store。** 各产物分在三层：

| 产物 | 存在哪 | 谁生成 | 怎么维护 |
|---|---|---|---|
| `<persistent-context>` | **Store（内存 dict）** | Tier 2 压缩时 `on_important()` 写入 | 追加，最多 10 条，永不压缩 |
| `<summary>` | **SummaryLayer（`_entries` 列表）** | Tier 3 压缩时 `summarizer.summarize()` | 滚动替换——每次 Tier 3 覆盖上一次 |
| `<file-cache>` | **FileCacheLayer（`OrderedDict`）** | 用户 Read 文件时 `on_file_read()` 触发 | LRU 淘汰，最多 20 个文件 |
| `<workspace-context>` | **WorkspaceLayer（自有字段）** | 事件触发（set_cwd/file_opened） | 实时刷新，不压缩 |
| `<memory-context>` | **MemoryStore（SQLite）** | 用户主动记忆 / 自动提取 | 每轮检索 top-5 |
| `[collapsed]` | **ConversationLayer（`messages[]`）** | Tier 2 压缩 | 对话层内原地替换 |

**关键信息不被压掉的原理：** 不是"压缩时小心点"，而是"压缩前就把它们搬到不会被压的地方"。Store 在 system prompt 里，ConversationLayer 是唯一被压缩的层。

### 追问：那中间压缩（Tier 2）的产物在对话层？先打分还是先压缩？怎么分段？

**回答：** 对，Tier 2 产物在对话层作为 `[collapsed]` 标记的普通 message。**打分和压缩同时进行**——一次 LLM 调用返回 JSON，同时包含 `summary` + `importance` + `key_facts`。不分开两步。分段详见第 6 节。

---

## 5. 只压缩对话层，其他层满了怎么办

### 问题

只压缩对话层，那其他层满了怎么办？

### 回答参考

当前确实有个架构缺口：

- **ConversationLayer**：有完整压缩链路（Budget → Policy → Pipeline）
- **FileCacheLayer**：LRU 淘汰，最多 20 文件，不会满
- **WorkspaceLayer**：open_files 截到 20 条，有硬上限
- **SummaryLayer**：滚动替换，只存 1 条，token 不涨
- **MemoryLayer**：max_entries=5，截断 300 字符，有硬上限
- **InstructionLayer**：`is_immutable=True`，不过问 budget

**最危险的是 InstructionLayer 的 `<persistent-context>`。** `persistent_facts` 每次 append，如果 set 成不设上限，每次压缩都往里加，system prompt 越来越胖。因为 `is_immutable=True`，BudgetManager 不对它做任何动作。

**缺口：** 各层有自己的硬上限（LRU、max_entries、滚动替换），但这些上限是写死的，不是基于 token budget 动态调整的。如果一个层既没有硬上限，又不是 conversation，就会偷偷涨到撑爆。

---

## 6. 上下文压缩的分段策略

### 问题

如何分段的？先打分后压缩还是先压缩后打分？

### 回答参考

**分段方式：** `_group_by_roundtrip()` 按 API round-trip 分组——每组以 assistant 消息开头，包含后面所有 tool_result，直到遇到下一条 assistant。一组刚好对应 LLM 的一次"思考 + 行动"回合。

分段后的处理：
```
groups = [g1, g2, g3, g4, g5, g6, g7, g8, g9, g10]
    │     └── head (keep_head=3) ── 保留原文
    │           g4, g5, g6, g7     ── LLM 压缩成 [collapsed]
    │           └── middle
    │                              g8, g9, g10 ── 保留原文
    │                              └── tail (keep_tail=3)
```

**打分和压缩同时进行：** 一次 LLM 调用返回 `{summary, importance, key_facts}`。`importance` 决定标签和是否写入 Store，不分开两步。

**改进方向：** 当前按 assistant 边界分段在多工具回合中过于碎片化。应改为按用户消息边界分组 + 超标（30000 字符）强制切分。纯文本 user 消息 = 新意图，含 tool_result 的 user 消息 = 接续当前组。不需要语义理解来识别意图，API 格式本身可区分。

---

## 7. 压缩后关键约束遗漏，如何发现和修正

### 问题

压缩后的摘要遗漏了关键约束，导致后续 Agent 做错了，怎么发现并修正？

### 回答参考

**当前运行时没有任何检测和修正机制。** 没有压缩后验证、没有回滚能力、没有 Agent 行为偏离检测。

**现有的防御：**
1. **`<persistent-context>`**：Store 存的 objective + key_facts 在 system prompt 里，不走压缩链路
2. **CollapseCircuitBreaker**：连续 3 轮 LLM 压缩失败则熔断，跳过 Tier 2/3
3. **保留 head/tail 原文**：头尾 3 组不压缩

**但都不防"摘要内容错误"。** 电路熔断器只防 API 调用失败，不防 LLM 写错了摘要。

**最务实的改进方案：行为偏离检测。** 不额外调 LLM，而是在 Agent 执行关键操作（`edit_file`/`write_file`）前快速自查：当前要做的修改和用户原始目标有没有矛盾。这比专门的压缩后验证成本低得多，且能覆盖校验规则写不出来的边界。

---

## 8. 长期记忆过时污染怎么处理

### 问题

如果长期记忆里保存了过时的文件摘要，后面 Agent 又拿它做判断，这种污染怎么处理？

### 回答参考

**当前系统只追踪"多久没访问"，不追踪"内容是否过时了"。** 有一个完整的 freshness 机制（指数衰减，半衰期 30 天），但它只回答"最近有没有人看过"，不回答"内容是否还准确"。

**场景没处理：** 第 1 天读了 auth.py 保存记忆"使用 basic auth"，第 3 天用户改成了 JWT，第 5 天新会话检索到旧记忆，基于错误信息做判断。

**FileCacheLayer 在文件被写时会 invalidate，但那是运行时缓存，不是长期记忆。** MemoryStore(SQLite) 不知道磁盘上对应的文件已经变了。

**三个改进方向：**

1. **写入时失效（源头治理）：** 已有 `on_file_write` 事件，但目前只 invalidate 了运行时 FileCacheLayer，缺少向长期记忆传播的步骤。

2. **检索时校验（使用时验证）：** 检索到文件摘要类记忆时，检查文件的 mtime 是否晚于记忆的 `created_at`。如果变了，大幅降低 freshness 或在渲染时附加 `[⚠️ 可能过时]` 警告。

3. **版本化失效：** stale 记忆不能直接用作事实，只能作为"候选线索"——提示 Agent 需要重新读文件验证。验证后更新为新版本，同时保留旧版本的失效原因，避免后续又被召回误用。

---

## 9. 多轮执行中反复读文件/调工具，怎么识别重复状态

### 问题

多轮执行中，Agent 可能反复读同一个文件或重复调用同一个工具。你是怎么识别重复状态的？

### 回答参考

**当前只记录，不阻断。** WorkspaceLayer 记录了 open_files 和 dirty_files，FileCacheLayer 缓存了文件内容和 hash，但没有机制告诉 Agent "这个文件你已经读过了，内容没变"。

**未处理的重复场景：** 重复读同一文件、重复调同一 shell 命令、重复尝试同样的失败方案。Agent 可能反复试同一个死路而不自知。

**改进方向：**

1. **幂等拦截（框架层）：** 对于 Read 类工具，如果文件 path 相同且 hash 没变，直接返回 cached content。FileCacheLayer 已有 hash，只差一个拦截 hook。

2. **失败重试检测（Agent 行为层）：** 记录 `(tool_name, args_hash) → status` 的调用历史。当 Agent 再次发起同样的调用时，在 tool_result 里附加 `[note: 上次结果: X]`，让 LLM 自己决定。

3. **判定条件：** 文件 hash 没变 + 两次读取之间没有中间写入事件 → 100% 是重复。不需要依赖"任务阶段"这种模糊概念。

### 追问："返回缓存摘要"是什么意思？上下文不是动态组装的吗？

**澄清：** 混淆在于"返回给谁"。返回缓存摘要是工具执行层的优化，不是 PromptBuilder 的改动。流程是：

```
LLM 调 read_file("auth.py")
  → 有缓存且 hash 没变
  → 不读磁盘，直接返回 FileCacheLayer 的缓存内容
  → LLM 不知道结果来自缓存
```

缓存节省的是磁盘 I/O 和网络传输，不能省 token（tool_result 里还是同样的内容）。真正省 token 的方式是让 LLM 少调工具——框架能做的只是给个提示标记。

---

## 10. 什么是 Agent Harness？和单纯调 LLM API 的区别

### 问题

你对 Agent Harness 怎么理解？它和单纯调用 LLM API 的区别是什么？

### 回答参考

**单纯调 LLM API** 是做一次推理——输入 prompt，输出 response，结束。下一轮是另一个独立会话，没有状态、没有记忆、没有工具。

**Agent Harness** 是让 LLM 处于一个受控的执行环境中持续运行：

```
                    ┌─ 状态管理 ← Store / 各 Layer
                    │
user msg → Harness →  ├─ 工具执行 ← ToolRegistry + Hook
                    │
                    ├─ 上下文治理 ← 三级压缩 + BudgetManager
                    │
                    ├─ 持久化 ← MemoryStore + RecoveryEngine
                    │
                    ├─ 安全边界 ← Hook 拦截 + Intent 分类
                    │
                    └─ LLM ← 只负责推理决策
```

**核心区别：** Harness 负责 LLM 之外的一切。LLM 在 Harness 里的角色被刻意缩小了——它只做决策和写作。其他所有事（什么时候压缩、压缩哪部分、用什么工具、怎样恢复现场、安全策略）是 Harness 的职责。

**最直接的测试：** 把同一个 LLM 放进你的 Harness 跑，和直接调 API 跑同样的任务，结果会很不一样——不是 LLM 变了，是 Harness 在 LLM 看不见的地方做了大量工作。这就是 Agent Harness 的价值。

---

## 11. Context Engineering / Prompt Engineering / Harness Engineering 区别

### 问题

介绍下 context engineering、prompt engineering、harness engineering

### 回答参考

**Prompt Engineering：** 写 LLM 看到的那段文字。system prompt 措辞、few-shot examples、输出格式约束（JSON schema）。效果直接，但不解决状态问题——prompt 写得再好，上下文太长 LLM 也会忽略中间内容。

**Context Engineering：** 决定 LLM 看到什么、看不到什么。不只是"塞什么进去"，还决定"什么时候把什么移出去"——压缩策略、分层组装、关键信息提取到 Store。Prompt 写得再好，如果关键决策被压缩丢了也没用；反过来，素材选对了，prompt 粗糙一点 LLM 也能干活。

**Harness Engineering：** 构建 LLM 所处的执行环境。工具注册和执行、状态管理、安全拦截、Hook 系统、失败恢复、审计日志、持久化。LLM 只是 harness 里的一个推理组件。Harness 可以换掉 LLM（从 Sonnet 换到 GPT-4o），大部分功能不受影响。

**三者关系：**
```
Harness Engineering（环境）
    ├── Context Engineering（素材管理）
    │       └── Prompt Engineering（文字表达）
    └── 工具系统、状态管理、安全、持久化...
```

**大部分 AI 应用只做了 prompt engineering。** 做 context engineering 的少一些。做 harness engineering 的更少——因为它和业务耦合最深，抽象不好就是一个巨大的 if/else 工厂。

---

## 12. ReAct 范式讲解

### 问题

讲解下 ReAct 范式

### 回答参考

**ReAct = Reasoning + Acting。** 核心循环是：LLM 思考 → 输出工具调用 → Harness 执行工具 → 结果放回对话 → LLM 继续思考 → 再调工具或给出最终回答。

```python
while True:
    response = llm_call(messages, system, tools, ...)   # Reasoning
    
    if response.stop_reason != "tool_use":
        return  # 思考完了，结束
    
    for block in response.content:                      # Acting
        if block.type == "tool_use":
            output = tools_registry.execute(tool_name, **tool_input)
    
    messages.append({"role": "user", "content": results})  # Observation
```

**和单纯调 API 的区别：** 纯 API 一次输出全部回答，不能调工具。ReAct 每次 tool_use 都是一次"思考→行动→观察"的循环，thinking 和 acting 交替进行。

**你的 Harness 在 ReAct 上加了什么：** 标准 ReAct 是 `Thought → Action → Observation → Thought → ...`，LLM 直接控制循环。你的 Harness 把循环控制权从 LLM 手里拿走了——Harness 决定什么时候给 LLM 看什么、什么时候压缩、什么时候阻断。LLM 只做推理和决策，不感知周边治理逻辑。

---

## 13. Agent 工作流范式对比

### 问题

Agent 工作流的不同范式对比

### 回答参考

**ReAct（你当前的范式）：**
- 每个 LLM 调用都是一次"思考→行动→观察"的循环
- 循环由 while True 控制，LLM 决定什么时候退出（stop_reason != tool_use）
- 简单、直接，适合工具密集型的编码任务
- 缺点：状态治理复杂（上下文增长快、需要压缩）

**Plan-and-Execute：**
- LLM 先规划（plan），然后执行（execute），然后反思（reflect）
- 不需要在每一步都调 LLM——一批工具执行完才调一次
- 适合长任务、多步骤的复杂场景
- 缺点：规划可能过期（执行中环境变化了），规划可能太粗糙

**Memory-augmented Agent：**
- 在 ReAct 或 Plan-and-Execute 基础上加记忆系统
- 短期记忆（对话上下文）+ 长期记忆（跨会话的 SQLite/向量存储）
- 你的代码同时实现了这两种

**对比：**

| 维度 | ReAct | Plan-and-Execute | Memory-augmented |
|---|---|---|---|
| 控制流 | LLM 驱动循环 | Plan → Execute → Reflect | 混合 |
| 状态管理 | 对话层承担 | Plan 承担 | 多层隔离 |
| 复杂任务 | 易迷失 | 适合 | 最适合 |
| 实现难度 | 低 | 中 | 高 |

你的代码选择了 ReAct + Memory-augmented 的混合：主循环是 ReAct，但加上了 Plan（TodoWrite）、Memory（MemoryStore）、Reflect（Store 持久化事实）的能力。

---

## 14. 过时记忆的版本化处理

### 补充问题

如果发现过时信息，你不会简单删除，而是更新为新版本？

### 回答参考

对。**不简单删除，保留旧版本+失效原因。** 因为删除只解决"不再用错"，保留失效原因解决"知道变化轨迹"。

**具体做法：**
- stale 记忆不能直接用作事实，只能作为候选线索——提示 Agent 需要重新读文件验证
- 验证后更新为新版本（通过 `entry.version.bump()`，已实现）
- 保留旧版本的失效原因（增加 `stale_reason` 字段）
- 避免后续检索再次误用（检索时 freshness 设成接近 0）

这样在调试时有完整的回溯链：哪条记忆过期了、它之前说了什么、实际发生了什么变化。三个记忆问题的共同主题——不信任自己的输出，要验证，错了能追。

---

## 核心设计理念总结

贯穿所有问题的三条设计原则：

1. **分层隔离**——Store、各 Layer、MemoryStore 互不干扰，通过 PromptBuilder 在调用前统一组装。ConversationLayer 是唯一被压缩的层。

2. **信任但验证**——当前偏信任（压缩不校验、记忆不过时检测），改进方向是加验证。亮点是重要性分级将关键信息搬出对话层。

3. **LLM 不感知 Harness 的存在**——压缩、缓存、budget 管理对 LLM 透明。LLM 只做推理决策，治理逻辑在 Harness 层。

**三个待改进的缺口（已被记录在记忆系统）：**
- 压缩后缺失校验（无回滚、无行为偏离检测）
- 分段策略待优化（assistant 边界太碎）
- 过时记忆检测缺失（只追踪新鲜度，不追踪内容准确性）
