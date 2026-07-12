# Context Engine 从零到精通（开发者教材）

> 这不是 API 文档，不是代码注释，也不是项目 README。  
> 这是一本教材，目标是让一个只有 Python 基础的人，彻底理解整个 Context Engine。

---

## 阅读前说明

**你需要的基础**
- 会 Python 基础语法（class、def、if、for、列表、字典）
- 能在命令行运行 `python main.py`
- 会用 VS Code 或任何编辑器打开文件跳转

**你不需要的基础**
- 不需要懂任何 AI Agent 知识
- 不需要懂任何设计模式
- 不需要懂任何软件架构术语

**本文的约定**
- 每个英文术语第一次出现时，都会按照下面的格式解释：
  1. 英文原文
  2. 中文翻译
  3. 一句话解释（像跟朋友聊天一样）
  4. 为什么会出现这个概念
  5. 本项目为什么需要它
  6. 在本项目中负责什么
  7. 一个生活中的例子

**代码定位格式**
- 每个类都会标注：`📁 文件路径` + `📍 类定义行号`
- 让你随时可以打开代码对照阅读

---

# 第一章：为什么会有 Context Engine？

## 1.1 从一个真实问题开始

假设你要用一个 AI 编程助手。你跟它说：

> "帮我找一个 bug，这个 bug 在用户登录的时候会出现。"

AI 助手需要知道什么才能回答你？

1. 你的项目目录在哪？（工作区信息）
2. 你的项目有哪些文件？（文件结构）
3. 你之前跟它聊过什么？（对话历史）
4. 你有没有告诉过它什么重要信息？（持久记忆）
5. 它之前帮你改过什么文件？（操作历史）

这些全部加起来，就是**上下文（Context）**。

---

### 术语解释：Context（上下文）

| 维度 | 说明 |
|------|------|
| 英文 | Context |
| 中文 | 上下文 |
| 一句话解释 | 让 AI 理解"现在是什么情况"所需要的全部信息 |
| 为什么出现 | AI 没有记忆，每次对话都是全新的。你必须把背景信息全部告诉它，它才知道怎么回答 |
| 本项目为什么需要 | Agent 需要知道项目结构、对话历史、文件内容、用户偏好，才能正确执行任务 |
| 在本项目中负责 | 由 Context Engine 统一管理，所有模块通过它获取和修改上下文 |
| 生活例子 | 你去医院看病，医生会先看你的病历（历史）、问你现在哪不舒服（当前状态）、查你的过敏史（约束条件）。这些信息加起来就是"就诊的上下文"。没有这些，医生没法给你开药 |

---

## 1.2 传统做法：全部塞进去

最简单的做法：把上面所有信息一股脑全部塞进提示词（Prompt，就是你发给 AI 的文字），发给大模型。

看起来很简单对吧？问题来了：

**问题一：上下文会越来越大**

```
第一轮对话：用户说了一句话 → 几百字
第十轮对话：积累了十轮对话 + 十个工具调用结果 → 几千字  
第五十轮对话：五十轮对话 + 文件内容 + 工具结果 → 几万字
第一百轮对话：...→ 直接超过大模型的输入上限
```

**问题二：不是所有信息都有用**

```
你跟 AI 聊了 50 轮，前 30 轮在讨论"怎么重构数据库"，
后 20 轮在讨论"怎么写前端页面"。

当 AI 在第 51 轮回答"前端按钮颜色"的问题时，
前 30 轮关于数据库的讨论不仅没用，还会干扰 AI 的判断。
```

**问题三：大模型有输入上限**

每个大模型都有最大输入长度限制（比如 20 万 token，约等于 15 万汉字）。超过限制，API 直接报错，对话就断了。

**问题四：每次调 API 都要花钱**

你发给大模型的文字越多，花的钱越多。如果把 5 万字的对话历史每次都发过去，而你只问了"今天天气怎么样"，那就是在烧钱。

---

### 术语解释：Token

| 维度 | 说明 |
|------|------|
| 英文 | Token |
| 中文 | 令牌 / 词元 |
| 一句话解释 | 大模型计费的基本单位，大约 1 个中文字 = 2 个 token，1 个英文单词 = 1.3 个 token |
| 为什么出现 | 大模型不是按"字"收费的，是按"词元"收费的。不同的模型有不同的 token 计算方式 |
| 本项目为什么需要 | 控制上下文大小的核心指标就是"用了多少 token"。预算（Budget）按 token 分配，压缩（Compression）按 token 触发 |
| 生活例子 | 就像发短信收费。短信按"条"收费，一条 70 字。Token 就是大模型的"一条短信"，但比短信更细粒度 |

---

### 术语解释：Prompt（提示词）

| 维度 | 说明 |
|------|------|
| 英文 | Prompt |
| 中文 | 提示词 |
| 一句话解释 | 你发给大模型的文字。所有对话、系统指令、工作区信息，拼在一起就是给大模型的提示词 |
| 为什么出现 | 大模型是一个"根据输入预测输出"的机器。提示词就是你给它的输入 |
| 本项目为什么需要 | Context Engine 的最终输出就是组装好的提示词 |
| 生活例子 | 你去餐厅点菜，说"不要辣，少盐，多加青菜"。这句话就是你的"提示词"。大模型就是厨房，根据你的提示词做菜 |

---

## 1.3 解决思路：分层管理 + 按需选择 + 智能压缩

Context Engine 用三个核心思路解决上面的问题：

**思路一：分层管理（Layer）**

不是把所有信息混在一起，而是分成不同的"层"：

- 系统指令层（永远不变的那部分）
- 对话层（跟用户的聊天记录）
- 工作区层（项目目录、git 分支等环境信息）
- 文件缓存层（最近读过的文件内容）
- 摘要层（压缩后的历史摘要）

每层独立管理，各管各的。

**思路二：按需选择（Selection）**

不是把所有层的内容都塞进提示词，而是：

1. 先收集所有可用的内容（Collect）
2. 按重要性排序（Rank）
3. 按 token 预算裁剪（Select）
4. 最后组装（Pack）

**思路三：智能压缩（Compression）**

当对话太长时，不是简单地删除旧消息，而是：

1. 第一层：清除旧工具调用结果（零成本，不调 LLM）
2. 第二层：对中间轮次打分，重要的保留，普通的压缩成摘要
3. 第三层：全量总结

---

## 1.4 一句话总结第一章

**Context Engine 解决的核心问题是：当对话越来越长时，如何在不超预算的前提下，把最重要的信息发给大模型。**

---

# 第二章：Context Engine 总体架构

## 2.1 整体架构图

```
                         用户输入
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                    main.py（入口）                        │
│  初始化所有模块 → 启动 REPL 循环 → 调用 agent_loop        │
└───────────────────────────┬───────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│              ContextOrchestrator（总调度器）              │
│  所有模块的统一入口。外部代码只跟它说话。                  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Layer Registry（层注册表）                          │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │ │
│  │  │Instruction│ │Workspace │ │FileCache │            │ │
│  │  │  Layer   │ │  Layer   │ │  Layer   │            │ │
│  │  └──────────┘ └──────────┘ └──────────┘            │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │ │
│  │  │ Memory   │ │ Summary  │ │Conversat.│            │ │
│  │  │  Layer   │ │  Layer   │ │  Layer   │            │ │
│  │  │ (M6)     │ │  (M3)    │ │  (M1)    │            │ │
│  │  └──────────┘ └──────────┘ └──────────┘            │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  M3: Budget + Compression（预算 + 压缩）            │ │
│  │  BudgetManager → CompressionPolicy → Pipeline        │ │
│  │  → MicroCompact → ContextCollapse → AutoCompact      │ │
│  │  → CircuitBreaker（熔断器）                          │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  M4: Selection Pipeline（选择管线）                  │ │
│  │  Collect → Rank → Select → Pack → PromptPackage      │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  M5: Observability + Recovery（可观测 + 恢复）      │ │
│  │  Serialize → Recovery → Audit → Dashboard → Replay  │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  PromptBuilder（提示词组装器）                       │ │
│  │  把上面所有内容拼成发给大模型的最终提示词             │ │
│  └─────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
                    发给大模型（LLM）
```

## 2.2 五层里程碑总览

Context Engine 按五个里程碑（M1-M5）逐步构建：

| 里程碑 | 名字 | 一句话解释 | 文件位置 |
|--------|------|-----------|----------|
| M1 | 基础框架 | 层 + 注册表 + 组装器 | `src/context/layers/`, `src/context/orchestrator.py`, `src/context/prompt_builder.py` |
| M2 | 工作区感知 | 感知项目目录、git 状态、最近读取的文件 | `src/context/layers/workspace.py`, `src/context/layers/file_cache.py` |
| M3 | 压缩 | 对话太长时自动压缩，有三层策略 + 熔断器 | `src/context/compression/`, `src/context/budget/` |
| M4 | 上下文选择 | 不是一股脑全塞，而是先收集 → 排序 → 选择 → 打包 | `src/context/selection/` |
| M5 | 可观测与恢复 | 保存/恢复状态，审计日志，性能仪表盘，历史回放 | `src/context/serialization/`, `src/context/recovery/`, `src/context/observability/`, `src/context/replay/` |

---

## 2.3 核心设计原则

**原则一：一个入口，一个出口**

- 所有入站请求通过 `ContextOrchestrator`（总调度器）
- 所有出站内容通过 `PromptBuilder`（提示词组装器）

你在系统里任何地方想操作上下文，只找 `orchestrator`。你想拿到组装好的提示词，只找 `PromptBuilder`。

**原则二：命令与查询分离**

- 问问题的（查询）不动手
- 做事情的（命令）不问问题

比如：
- `BudgetManager.check()` 只算账、不做决定
- `CompressionPolicy.evaluate()` 只做决定、不动手
- `CompressionPipeline.execute()` 只动手、不算账

**原则三：可插拔**

每个核心组件都定义了抽象基类（ABC，Abstract Base Class，抽象基类——你可以理解为"接口"，约定了必须实现哪些方法），你可以随时替换实现。

---

### 术语解释：抽象基类（ABC / Abstract Base Class）

| 维度 | 说明 |
|------|------|
| 英文 | Abstract Base Class |
| 中文 | 抽象基类 |
| 一句话解释 | 一个"合同"——规定了子类必须实现哪些方法，但自己不动手 |
| 为什么出现 | 让不同的人写的代码可以互换。只要遵守同一个"合同"，怎么实现都行 |
| 本项目为什么需要 | 方便你以后替换组件。比如你可以写一个新的 Compressor，只要实现 `compress()` 方法就行 |
| 生活例子 | 肯德基的"炸鸡标准流程"。全世界的肯德基用的鸡不一样、油不一样，但"腌制→裹粉→油炸→沥油"这个流程是一样的。这个流程就是"抽象基类" |

---

## 2.4 一句话总结第二章

**Context Engine 像一个六层汉堡：顶层总调度 + 六种馅料（层）+ 自动减肥（压缩）+ 挑食（选择）+ 黑匣子（可观测）。**

---

# 第三章：一次用户请求的完整生命周期

## 3.1 从输入到输出的全流程

这是整个系统最重要的章节。我们从一个用户输入开始，跟踪它经历的每一步。

**场景**：用户在 REPL 里输入 `"帮我找一个 bug，在 src/agent/loop.py 里"`

---

### 第一步：REPL 接收输入

```
📁 main.py 第 482 行
```

用户在终端输入文字，Python 的 `input()` 函数接收。

输入：`"帮我找一个 bug，在 src/agent/loop.py 里"`
输出：一个字符串

---

### 第二步：UserPromptSubmit 钩子

```
📁 main.py 第 495 行
```

在把用户输入发给大模型之前，先跑一遍钩子（Hook）。

---

### 术语解释：Hook（钩子）

| 维度 | 说明 |
|------|------|
| 英文 | Hook |
| 中文 | 钩子 / 挂钩 |
| 一句话解释 | 在流程的特定位置预先挂一个函数，到了这个位置自动执行 |
| 为什么出现 | 让你在不修改核心代码的前提下，在关键节点插入自己的逻辑 |
| 本项目为什么需要 | 允许在"用户说话前"、"工具执行前"、"工具执行后"、"系统停止时"插入自定义逻辑 |
| 生活例子 | 你出门前要"检查钥匙、手机、钱包"。你妈在你门口贴了一张便签"出门前记得带伞"。你每次开门都看到这张便签，这就是一个钩子 |

---

钩子可以干三件事：
1. 放行（用户输入原样通过）
2. 拦截（直接拒绝，比如检测到危险命令）
3. 追加上下文（在用户输入后面加一段补充信息）

本例中：钩子放行，用户输入原样通过。

---

### 第三步：存入对话历史

```
📁 main.py 第 503 行
orchestrator.add_message("user", query)
```

用户的消息被追加到对话历史中。`orchestrator`（总调度器）维护着一个消息列表。

此时消息列表的状态：
```python
messages = [
    ... 之前的对话 ...
    {"role": "user", "content": "帮我找一个 bug，在 src/agent/loop.py 里"}
]
```

---

### 第四步：调用 agent_loop

```
📁 main.py 第 506-516 行
```

`agent_loop()` 是执行循环的入口。它接受 `orchestrator` 作为参数。

---

### 第五步：压缩检查（tick）

```
📁 src/agent/loop.py 第 132-150 行（大致位置）
orchestrator.tick()
```

这是"每次循环前检查一下要不要压缩"的入口。流程如下：

```
orchestrator.tick()
  │
  ├─ Step 1: BudgetManager.check(layers)
  │   纯算账。返回"每个层用了多少 token，还剩多少"
  │
  ├─ Step 2: CompressionPolicy.evaluate(reports)
  │   纯做决定。看报告 → 匹配规则 → 返回"要不要压缩，怎么压缩"
  │
  └─ Step 3: CompressionPipeline.execute(plan)
      真动手。按计划执行 1-3 层压缩
      ├─ MicroCompactStage: 清除旧工具结果
      ├─ ContextCollapseStage: 对中间轮次打分+摘要
      └─ AutoCompactStage: 全量总结
```

如果对话没超预算，这三个步骤很快返回"不需要压缩"。

---

### 第六步：组装提示词

```
📁 src/agent/loop.py 第 155-175 行（大致位置）
orchestrator.build_prompt()
```

这一步把各类信息拼成发给大模型的最终提示词。

如果启用了 M4 选择管线（本项目已启用）：

```
SelectionPipeline.run(ctx)
  │
  ├─ Phase 1 Collect（收集）
  │   6 个 Collector 各自产生 Candidate
  │   ├─ InstructionCollector → 系统指令候选
  │   ├─ WorkspaceCollector   → 工作区候选
  │   ├─ MemoryCollector      → 记忆候选
  │   ├─ SummaryCollector     → 摘要候选
  │   ├─ FileCacheCollector   → 文件缓存候选
  │   └─ ConversationCollector → 对话候选
  │
  ├─ Phase 2 Rank（排序）
  │   PriorityRanker 按优先级排序
  │
  ├─ Phase 3 Select（选择）
  │   按 token 预算裁剪
  │   指令层 10% 必须保留 (reserved=True)
  │   对话层 60% 用完就截断
  │
  └─ Phase 4 Pack（打包）
      真正加载内容，组装 PromptPackage
```

`PromptBuilder` 收到 `PromptPackage` 后，渲染成大模型 API 需要的格式。

最终输出：
```python
{
    "system": "你是一个编程助手...\n当前工作目录: D:/s_full\n...",
    "messages": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
        ...
    ]
}
```

---

### 第七步：调用大模型

```
📁 src/agent/loop.py 第 207-215 行
client.messages.create(...)
```

组装好的提示词发给 Anthropic API。

大模型返回一个响应，可能包含：
- 纯文本回复（对话结束）
- 工具调用请求（比如"我需要用 read_file 读取 loop.py"）

---

### 第八步：处理工具调用

如果大模型要求执行工具（比如 `read_file`）：

```
PreToolUse 钩子 → 检查/拦截/修改工具调用
  ↓
registry.execute(name, **input) → 真正执行工具
  ↓
PostToolUse 钩子 → 工具执行后的处理
  ↓
M2 事件 → 通知 orchestrator（"读了一个文件"、"改了一个文件"）
  ↓
工具结果追加到 messages，回到第五步，继续循环
```

---

### 第九步：大模型不再要工具了

大模型返回纯文本 → Stop 钩子执行 → 循环结束 → 结果打印给用户。

---

## 3.2 完整时序图

```
用户 ──→ REPL ──→ Hook(PreSubmit) ──→ orchestrator.add_message("user")
                                            │
                                            ▼
                                      agent_loop()
                                         │
                                    ┌────┴────┐
                                    │ tick()  │ ← 每轮循环都检查
                                    │ 压缩检查 │
                                    └────┬────┘
                                         │
                                    ┌────┴────┐
                                    │ build() │ ← 每轮循环都重建
                                    │ 组装提示词│
                                    └────┬────┘
                                         │
                                    ┌────┴────┐
                                    │ LLM API │ ← 真正调大模型
                                    └────┬────┘
                                         │
                              ┌──────────┴──────────┐
                              │                      │
                          有工具调用              无工具调用
                              │                      │
                         ┌────┴────┐            ┌────┴────┐
                         │执行工具  │            │Stop 钩子│
                         │M2 事件  │            │返回结果  │
                         └────┬────┘            └─────────┘
                              │
                              ▼
                         回到 tick()
```

---

## 3.3 关键中间对象的变化

在整个过程中，这些对象被创建和修改：

| 对象 | 创建时机 | 修改时机 | 生命周期 |
|------|---------|---------|---------|
| `messages` 列表 | main.py 初始化时 | 每次用户说话、每次 LLM 回复、每次工具调用 | 整个进程存活期 |
| `BudgetReport` | 每次 `tick()` | 不修改，每次新建 | 一次 `tick()` 调用 |
| `CompressionPlan` | `CompressionPolicy.evaluate()` | 不修改 | 一次压缩决策 |
| `PromptPackage` | 每次 `build_prompt()` | 不修改 | 一次提示词组装 |
| `SelectionResult` | 每次 `SelectionPipeline.run()` | 不修改 | 一次选择 |

---

## 3.4 思考题

1. 如果去掉 `tick()` 这一步，系统会发生什么？
2. 为什么提示词要"每次循环都重建"？能不能缓存上一次的？
3. 工具执行后的结果是怎么影响下一轮 LLM 调用的？（提示：想想 `messages` 列表里多了什么）
4. 如果一个工具执行了很长时间（比如跑了 5 分钟的 bash 命令），`tick()` 会等它吗？

---

## 3.5 一句话总结第三章

**一次用户请求经历：输入 → 钩子 → 存消息 → 压缩检查 → 组装提示词 → 调大模型 → 执行工具 → 再调大模型 → 直到大模型说完了 → 返回结果。**

---

# 第四章：M1 深度讲解——基础框架

## 4.1 M1 包含什么

M1 是 Context Engine 的骨架。没有它，后面的 M2-M5 无从搭建。

M1 包含四个核心组件：

| 组件 | 作用 | 文件 |
|------|------|------|
| `ContextOrchestrator` | 总调度器，所有模块的统一入口 | `src/context/orchestrator.py` |
| `PromptBuilder` | 提示词组装器，把各层内容拼成最终提示词 | `src/context/prompt_builder.py` |
| `BaseLayer` | 所有层的"合同"（抽象基类） | `src/context/layers/base.py` |
| `Layer Registry` | 层注册表，管理层的顺序 | 在 `orchestrator.py` 内部 |

以及两个具体的层：
- `InstructionLayer`：不可变的系统指令
- `ConversationLayer`：对话历史

---

## 4.2 ContextOrchestrator——总调度器

```
📁 src/context/orchestrator.py
```

---

### 术语解释：Orchestrator（调度器）

| 维度 | 说明 |
|------|------|
| 英文 | Orchestrator |
| 中文 | 调度器 / 编排器 |
| 一句话解释 | 像一个乐队的指挥，协调所有乐器（模块）一起演奏 |
| 为什么出现 | 当系统有很多模块时，需要一个总指挥来协调谁先谁后、数据怎么流动 |
| 本项目为什么需要 | 这是整个 Context Engine 的唯一入口。外部代码只需要跟它打交道 |
| 生活例子 | 拍电影的导演。导演不需要自己扛摄像机、不需要自己打灯光，但他知道每场戏谁该上场、拍完这场下一场是什么 |

---

### 它做什么？

`ContextOrchestrator` 拥有三个核心职责：

1. **管理层的注册表**：决定有哪些层、按什么顺序排列
2. **触发压缩流程**：`tick()` 方法 → 预算检查 → 压缩决策 → 执行压缩
3. **触发提示词组装**：`build_prompt()` 方法 → 走选择管线 → 组装最终提示词

还有一个重要功能：**事件通知**

```
on_file_read(path)       → 通知 FileCacheLayer 缓存文件内容
on_file_write(path)      → 通知 FileCacheLayer 更新缓存
on_directory_changed(cwd) → 通知 WorkspaceLayer 更新工作目录
```

---

### 代码定位

| 关注点 | 位置 |
|--------|------|
| 类定义 | `orchestrator.py` `class ContextOrchestrator` |
| `__init__` 初始化 | 构造函数，接收所有依赖 |
| `tick()` 方法 | 压缩检查的入口 |
| `build_prompt()` 方法 | 提示词组装的入口 |
| `add_message()` 方法 | 追加消息到对话层 |
| `on_file_read/write/directory_changed` | M2 事件处理 |

---

### 为什么这样设计？

**问题：为什么不直接让 agent_loop 调用各个模块，而非要通过一个 Orchestrator？**

答案：**单一入口原则。**

```
❌ 坏的设计（没有 Orchestrator）：
agent_loop 需要知道：
  - 有哪些 Layer
  - 每个 Layer 怎么读怎么改
  - 压缩怎么触发
  - 选择管线怎么配置
  → agent_loop 太复杂了，而且每次加新功能都要改 agent_loop

✅ 好的设计（有 Orchestrator）：
agent_loop 只需要知道：
  - orchestrator.tick()       → 压缩检查
  - orchestrator.build_prompt() → 组装提示词
  - orchestrator.add_message()  → 加消息
  → agent_loop 很简单，新功能加在 orchestrator 内部
```

---

### 初始化顺序——层的位置很关键

`orchestrator` 初始化时，层的注册顺序决定了最终提示词的组装顺序：

```
位置 0: InstructionLayer     (最先)
位置 1: WorkspaceLayer       (然后是环境信息)
位置 2: FileCacheLayer       (然后是缓存的文件)
位置 3: MemoryLayer (M6)    (然后是记忆)
位置 4: SummaryLayer          (然后是历史摘要)
位置 5: ConversationLayer     (最后是对话)
```

**为什么这个顺序？**
- 系统指令放在最前面（大模型最先看到，权重最高）
- 对话放在最后（最近的对话最重要）
- 中间放各种辅助信息

---

## 4.3 PromptBuilder——提示词组装器

```
📁 src/context/prompt_builder.py
```

---

### 术语解释：Builder（组装器 / 建造者）

| 维度 | 说明 |
|------|------|
| 英文 | Builder |
| 中文 | 组装器 / 建造者 |
| 一句话解释 | 把零散的零件按固定规则拼成一个完整的成果 |
| 为什么出现 | 组装逻辑应该集中在一个地方，而不是散落在各个模块里 |
| 本项目为什么需要 | 把各层内容统一拼成 LLM API 需要的格式 |
| 生活例子 | 宜家家具的安装说明书。每块板子（层）是独立的，但安装说明书（Builder）告诉你按什么顺序、怎么拼 |

---

### 它做什么？

两种工作模式：

**传统模式**（M1-M3）：遍历所有层，每个层渲染自己的内容，拼起来。

**选择模式**（M4+）：从 `SelectionPipeline` 获取 `PromptPackage`，按 package 组装。

组装规则：
- 第一个渲染出字符串的层 → 作为系统提示词（system prompt）
- 所有渲染出消息列表的层 → 合并为消息列表（messages）

---

### 代码定位

| 关注点 | 位置 |
|--------|------|
| `build()` | 传统模式，遍历层 |
| `build_from_package()` | M4 模式，从 PromptPackage 组装 |
| 渲染规则 | 第一个 str → system，list[dict] → messages |

---

## 4.4 Layer（层）——内容的最小单位

```
📁 src/context/layers/base.py
```

---

### 术语解释：Layer（层）

| 维度 | 说明 |
|------|------|
| 英文 | Layer |
| 中文 | 层 |
| 一句话解释 | 一层一层的馅料，每种馅料独立管理，最后叠在一起 |
| 为什么出现 | 不同类型的上下文不应该混在一起。系统指令是一种，对话是一种，文件缓存又是一种 |
| 本项目为什么需要 | 每层有自己的存储方式、自己的渲染方式、自己的生命周期 |
| 生活例子 | 汉堡。面包是一层，肉饼是一层，生菜是一层，芝士是一层。你可以单独换掉肉饼而不影响面包。每层各管各的 |

---

### BaseLayer——所有层的"合同"

```python
class BaseLayer(ABC):
    def render(self) -> LayerContent:
        """把这一层的内容转换成可组装的形式"""
        ...
```

`LayerContent` 可以是：
- 一个字符串 → 作为系统提示词的一部分
- 一个消息列表 → 追加到对话消息中
- 空 → 这层不参与本轮提示词

每个具体的层（InstructionLayer、ConversationLayer 等）都遵守这个合同，实现自己的 `render()`。

---

### InstructionLayer——不可变的系统指令

```
📁 src/context/layers/instruction.py
```

存储系统提示词（比如"你是一个编程助手"），一旦设置不再改变。

**为什么不可变？** 系统提示词是大模型的"角色设定"，频繁改动会让大模型行为不稳定。

---

### ConversationLayer——对话历史

```
📁 src/context/layers/conversation.py
```

存储用户和 AI 之间的所有对话消息。先进先出（FIFO）。

**为什么是最灵活的？** 对话每时每刻都在变化，用户说一句、AI 回一句、工具调一次，都在追加消息。

---

## 4.5 M1 的数据流动

```
各 Layer 存储数据（各自独立维护）
       │
       ▼
PromptBuilder.build() 遍历各层
       │
       ├─ InstructionLayer.render()  → "你是一个编程助手..."
       │   第一个 str → system prompt
       │
       ├─ ConversationLayer.render() → [{"role": "user", ...}, ...]
       │   list[dict] → 追加到 messages
       │
       ▼
BuildResult {
    system: "你是一个编程助手...",
    messages: [{"role": "user", ...}, ...]
}
```

---

## 4.6 思考题

1. 为什么 `InstructionLayer` 是不可变的，而 `ConversationLayer` 是不断增长的？
2. 如果把系统提示词也放在 `ConversationLayer` 里（作为第一条消息），会有什么不同？
3. `LayerContent` 可以是空值。什么时候一个层会返回空？
4. 如果现在要加一个"天气信息层"（显示当前天气），你需要做什么？提示：只需要实现 `render()`

---

## 4.7 一句话总结第四章

**M1 是骨架——确定了"层"这个核心概念和"总调度器"这个统一入口，后面的 M2-M5 都在这副骨架上长肉。**

---

# 第五章：M2 深度讲解——工作区感知

## 5.1 M2 解决了什么问题？

M1 只知道"系统指令"和"对话历史"。但 AI 编程助手还需要知道：

- 项目根目录在哪？（`/home/user/myproject`）
- 用的是什么 git 分支？（`main` / `feature-login`）
- 项目有哪些文件？
- 最近读了哪些文件？内容是什么？

这些信息叫**工作区上下文**。M2 就是让 Context Engine 感知这些信息。

---

## 5.2 WorkspaceLayer——工作区信息

```
📁 src/context/layers/workspace.py
```

### 它存什么？

```python
{
    "cwd": "/home/user/myproject",   # 当前工作目录
    "git_branch": "main",            # 当前 git 分支
    "git_status": "clean",           # git 状态（有没有未提交的改动）
    "os": "linux",                   # 操作系统
}
```

### 它怎么更新？

```
agent_loop 执行 bash 命令时，如果命令里有 cd：
  → on_directory_changed("/新的目录")
  → WorkspaceLayer 更新 cwd 和 git 信息
```

### 【小白解释】

> 就像你打开 VS Code 时，左下角会显示当前文件夹路径和 git 分支。WorkspaceLayer 就是干这个的，只不过它是给 AI 看的。

---

## 5.3 FileCacheLayer——文件缓存

```
📁 src/context/layers/file_cache.py
```

### 它解决什么问题？

AI 编程助手经常需要读文件。如果每次都要从磁盘读，太慢了。而且 AI 需要知道"我最近读了哪些文件"，这本身就是有价值的上下文。

### 它怎么工作？

1. 当 AI 调用 `read_file` 工具时 → `orchestrator.on_file_read(path, content)` → 存入 FileCacheLayer
2. 当 AI 调用 `write_file` 或 `edit_file` 时 → `orchestrator.on_file_write(path)` → 刷新缓存
3. 当组装提示词时 → FileCacheLayer 渲染最近读过的文件列表 + 内容摘要

### 缓存策略

```
最大缓存文件数: 20 个
每个文件最大行数: 150 行
超过限制时: 淘汰最久没访问的（LRU 算法）
```

---

### 术语解释：LRU（最近最少使用）

| 维度 | 说明 |
|------|------|
| 英文 | LRU (Least Recently Used) |
| 中文 | 最近最少使用 |
| 一句话解释 | 空间不够时，踢掉最久没被访问的那个 |
| 为什么出现 | 缓存的存储空间有限，需要一种策略决定删谁 |
| 本项目为什么需要 | FileCacheLayer 最多缓存 20 个文件，超出时淘汰最旧的 |
| 生活例子 | 冰箱放不下了，你会扔掉最久没吃的那盒剩菜 |

---

## 5.4 M2 事件驱动机制

M2 的核心创新：**让 agent_loop 在执行工具时通知 orchestrator**。

```
agent_loop 执行工具:

  read_file(path)  → orchestrator.on_file_read(path, content)
  write_file(path) → orchestrator.on_file_write(path)
  edit_file(path)  → orchestrator.on_file_write(path)
  bash("cd xxx")   → orchestrator.on_directory_changed("xxx")
```

这些事件让 Context Engine 始终保持对环境的感知，而不是每次重新扫描。

---

### 术语解释：Event-Driven（事件驱动）

| 维度 | 说明 |
|------|------|
| 英文 | Event-Driven |
| 中文 | 事件驱动 |
| 一句话解释 | 不是"一直盯着等变化"，而是"有变化了通知我一声" |
| 为什么出现 | 轮询（一直问"变了吗变了吗"）效率太低。事件驱动只在变化发生时触发 |
| 本项目为什么需要 | agent_loop 执行工具时，通知 orchestrator 更新上下文，而不是 orchestrator 不停扫描文件系统 |
| 生活例子 | 快递到了，快递员给你发短信（事件驱动），而不是你每 5 分钟下楼看一眼（轮询） |

---

## 5.5 M2 的数据流动

```
agent_loop 执行工具
       │
       ├─ read_file → on_file_read
       │               └→ FileCacheLayer 缓存文件内容
       │
       ├─ write_file → on_file_write
       │               └→ FileCacheLayer 标记缓存失效
       │
       └─ bash("cd xxx") → on_directory_changed
                            └→ WorkspaceLayer 更新 cwd + git
       │
       ▼
每次 build_prompt() 时:
  WorkspaceLayer.render()  → "当前目录: D:/s_full, 分支: main"
  FileCacheLayer.render()  → "最近读取的文件: [loop.py, main.py, ...]"
```

---

## 5.6 思考题

1. 如果 FileCacheLayer 不限制最大文件数，会发生什么？
2. WorkspaceLayer 里的 git 信息是在什么时候更新的？是实时查询还是事件触发？
3. 如果 AI 用 `bash` 命令读了文件（比如 `cat main.py`），FileCacheLayer 会感知到吗？
4. 为什么需要 `on_file_write` 事件？文件被修改后不更新缓存会有什么后果？

---

## 5.7 一句话总结第五章

**M2 让 Context Engine 长了"眼睛"和"耳朵"——它知道你在哪个目录、用哪个分支、最近读了哪些文件，而且这些信息是实时更新的。**

---

# 第六章：M3 深度讲解——预算与压缩

M3 是整个 Context Engine 最复杂、也最精妙的部分。

## 6.1 问题场景

假设你跟 AI 聊了 100 轮对话。每轮大约 500 字。那么对话历史就是 5 万字。

你问第 101 个问题："帮我看看这个变量名起得好不好"——这个问题本身只需要前 2 轮的上下文就够了。

但你如果把这 5 万字全部发给大模型：
1. 花更多的钱（token 计费）
2. 可能超出大模型的输入上限
3. 前 80 轮无关的对话会干扰大模型理解你的问题

M3 就是来解决这个问题的。

---

## 6.2 M3 的设计哲学：四权分离

M3 最核心的设计原则是：**把四个职责分给四个类**。

| 类 | 职责 | 有权做什么 | 无权做什么 |
|----|------|-----------|-----------|
| `BudgetManager` | 算账 | 查每个层用了多少 token | 不能决定是否压缩 |
| `CompressionPolicy` | 决策 | 根据规则决定要不要压缩 | 不能动手压缩 |
| `CompressionPipeline` | 执行 | 按计划执行压缩操作 | 不能决定策略 |
| `CircuitBreaker` | 保护 | 压缩连续失败就熔断 | 不参与正常流程 |

**为什么这样分？**

如果不能分开：
- 算账跟决策混在一起 → 换一种触发规则就要改整个代码
- 决策跟执行混在一起 → 换一种压缩算法就要改决策逻辑
- 没有熔断器 → LLM 连续失败时反复重试，浪费大量费用

---

### 术语解释：CircuitBreaker（熔断器）

| 维度 | 说明 |
|------|------|
| 英文 | Circuit Breaker |
| 中文 | 熔断器 / 断路器 |
| 一句话解释 | 当某个操作连续失败太多次时，自动跳过它，过一段时间再重试 |
| 为什么出现 | 防止连续的失败浪费资源。在电路里，电流过载时自动跳闸 |
| 本项目为什么需要 | LLM 调用可能连续失败（网络问题、API 故障），如果不熔断，每次压缩都会重试 → 浪费钱 + 拖慢速度 |
| 生活例子 | 家里的电闸。电器短路时电闸跳掉，保护整个电路不被烧坏。过一会儿你推上去，如果还跳，说明问题没解决 |

---

## 6.3 BudgetManager——算账的

```
📁 src/context/budget/manager.py
```

### 它做什么？

```python
reports = budget_mgr.check(layers)
# 返回：[
#   BudgetReport("instruction", used=500, limit=10000, ratio=0.05),
#   BudgetReport("conversation", used=85000, limit=90000, ratio=0.94),
#   ...
# ]
```

**只描述事实，不做任何决定。**

### 什么是 Budget？

---

### 术语解释：Budget（预算）

| 维度 | 说明 |
|------|------|
| 英文 | Budget |
| 中文 | 预算 |
| 一句话解释 | 给每种内容分配一个 token 上限，超了就触发处理 |
| 为什么出现 | 大模型有输入上限，每轮调用的 token 不是无限的，必须分配 |
| 本项目为什么需要 | 决定"系统指令占多少"、"对话占多少"、"文件缓存占多少" |
| 生活例子 | 旅游预算。总共 1 万块，住宿 3000、吃饭 2000、门票 1500、交通 2000、购物 1500。每项花多少心里有数，超了就调整 |

---

### 本项目中的预算分配

```python
# main.py 第 329-335 行
BudgetPolicy([
    BudgetAllocation("instruction", 0.10),   # 系统指令: 10%
    BudgetAllocation("workspace", 0.05),      # 工作区: 5%
    BudgetAllocation("memory", 0.05),         # 记忆: 5%
    BudgetAllocation("file_cache", 0.05),     # 文件缓存: 5%
    BudgetAllocation("summary", 0.15),        # 摘要: 15%
    BudgetAllocation("conversation", 0.60),   # 对话: 60%
])
```

如果总预算 100,000 token：对话层最多占 60,000 token。

---

## 6.4 CompressionPolicy——做决策的

```
📁 src/context/compression/policy.py
```

### 它做什么？

```python
reports = budget_mgr.check(layers)    # 先看账单
plan = compression_policy.evaluate(reports)  # 再决定要不要压缩
# 返回：CompressionPlan(max_tier=3, target_ratio=0.50)
# 或：None（不需要压缩）
```

### 规则是怎么匹配的？

`OverBudgetRule` 是默认规则：

```
条件：对话层连续 2 次超出预算 10% 以上
动作：执行最多到第 3 层的压缩，把对话层压到 50%
```

**为什么要求"连续 2 次"而不是"一次就压"？**
防止边界情况导致频繁压缩。比如对话刚好在预算线上跳动，如果一次超就压，会导致"压缩 → 刚好够 → 下一轮又超 → 又压缩"的抖动。

---

### 术语解释：Policy（策略）

| 维度 | 说明 |
|------|------|
| 英文 | Policy |
| 中文 | 策略 / 政策 |
| 一句话解释 | 一组"如果...就..."的规则，根据情况自动做决定 |
| 为什么出现 | 把做决定的逻辑集中管理，方便修改 |
| 本项目为什么需要 | 决定什么时候触发压缩、压缩到什么程度 |
| 生活例子 | 公司的报销政策。"金额小于 500 的，部门经理签字就行；超过 500 的，需要总监签字"。这就是一个 Policy |

---

## 6.5 CompressionPipeline——动手的

```
📁 src/context/compression/pipeline.py
```

### 它做什么？

接受 `CompressionPlan`，按计划执行压缩。

### 三层压缩详解

```
📁 src/context/compression/stages.py
```

---

### 第一层：MicroCompactStage（微压缩）

**触发条件**：总是最先执行（零成本）
**做什么**：清除旧轮次中的大段工具调用结果

```
压缩前:
  {"role": "assistant", "content": [tool_use: read_file("main.py")]}
  {"role": "user", "content": [tool_result: {整个 main.py 的全文，3000 行}]}

压缩后:
  {"role": "assistant", "content": [tool_use: read_file("main.py")]}
  {"role": "user", "content": [tool_result: "[content cleared — 3000 lines]"]}
```

**为什么不直接删掉？** 保留消息结构（让大模型知道"我确实读过这个文件"），但删掉具体内容（省 token）。

**为什么零成本？** 不调 LLM，纯字符串处理。

---

### 术语解释：Stage（阶段）

| 维度 | 说明 |
|------|------|
| 英文 | Stage |
| 中文 | 阶段 |
| 一句话解释 | Pipeline 中的一个步骤。每个 Stage 负责一种处理 |
| 为什么出现 | 把复杂流程拆成多个小步骤，每个步骤简单明了 |
| 本项目为什么需要 | 三层压缩分别用三个 Stage，独立运行、独立判断 |
| 生活例子 | 洗车流水线：预洗（冲掉大块泥）→ 泡沫洗 → 清水冲 → 擦干。每个阶段做一件事 |

---

### 第二层：ContextCollapseStage（对话折叠）

**触发条件**：T1 没解决问题，需要进一步压缩
**做什么**：把对话分成一个个"轮次组"，送给 LLM 打分

```
分组逻辑：
  一组 = 一条 assistant 消息 + 它后面所有的 tool_result
  例如：
    AI 说"我先读一下文件" → 调 read_file → 得到结果
    这是一组

打分输出（LLM 返回 JSON）：
  {
    "summary": "用户要求查看 main.py 的入口函数",
    "importance": "intermediate_step",
    "key_facts": ["main.py 包含 main() 函数", "main() 里初始化了上下文引擎"]
  }
```

五个重要性等级：

| 等级 | 含义 | 处理方式 | 生活例子 |
|------|------|---------|---------|
| `goal_declaration` | 用户改变了主要目标 | 写入持久存储，永远不丢 | "我们不做网站了，改做手机 APP" |
| `error_fix` | 发现并修复了错误 | 写入持久存储 | "找到 bug 了：第 42 行少了个参数" |
| `decision_made` | 做了架构决策 | 写入持久存储 | "决定用 PostgreSQL 而不是 MySQL" |
| `intermediate_step` | 普通工作步骤 | 压缩成一句话摘要 | "读了一下 main.py 看看结构" |
| `chitchat` | 闲聊 | 大幅压缩，基本只留关键词 | "好的"、"明白了" |

**重要信息被写入 `Store`，即使后续再压缩也不会丢失。**

---

### 第三层：AutoCompactStage（自动全量压缩）

**触发条件**：T2 还不行，对话实在太长了
**做什么**：调 LLM 把整个对话历史总结成一段文字，存入 `SummaryLayer`

```
压缩后：
  ConversationLayer 截断（只保留最近 5 轮）
  SummaryLayer 追加一条：{整个历史对话的摘要}
```

---

## 6.6 熔断器

```
📁 src/context/compression/circuit_breaker.py
```

### 三态状态机

```
        正常状态              故障状态            半开状态
     ┌──────────┐        ┌──────────┐        ┌──────────┐
     │  CLOSED  │  连续   │   OPEN   │  60秒  │HALF_OPEN │
     │   (闭合)  │──失败3次→│  (断开)   │──超时后→│  (半开)   │
     │ 正常通行  │        │ 拒绝请求  │        │ 试探一次  │
     └──────────┘        └──────────┘        └──────────┘
          ↑                                        │
          └──────────试探成功（关闭）────────────────┘
                    试探失败 → 回到 OPEN
```

- CLOSED：一切正常，压缩正常执行
- OPEN：连续 3 次失败，跳过 T2 和 T3（T1 不受影响，因为它不调 LLM）
- HALF_OPEN：等待 60 秒后，允许一次试探。成功就回到 CLOSED，失败就继续 OPEN

**为什么 T1 不受影响？** T1 不调 LLM，没有失败的可能。所以熔断器只在 T2/T3 的 `can_run()` 方法里检查。

---

## 6.7 M3 完整数据流

```
orchestrator.tick()
       │
       ▼
BudgetManager.check(layers)  ←── 纯查询，返回各层 token 用量
       │
       ▼
CompressionPolicy.evaluate(reports)  ←── 纯决策，返回 CompressionPlan
       │
       ├── 不需要压缩 → 直接返回
       │
       └── 需要压缩 →
              │
              ▼
       CompressionPipeline.execute(plan)
              │
              ├── T1: MicroCompactStage
              │   └── 清除旧 tool_result（零成本）
              │
              ├── T2: ContextCollapseStage
              │   ├── 熔断器检查 can_run()
              │   ├── 消息分组 → LLM 打分
              │   └── 重要消息 → on_important 回调 → Store
              │
              └── T3: AutoCompactStage
                  ├── 熔断器检查 can_run()
                  ├── LLM 全量摘要
                  └── 摘要 → SummaryLayer
```

---

## 6.8 思考题

1. 为什么 Budget 要放在 Compression 前面，而不是反过来？
2. 如果去掉 T1（MicroCompact），直接执行 T2，会有什么损失？
3. 熔断器打开后，对话继续增长怎么办？
4. `goal_declaration` 级别的消息写入 Store 后，Store 里最多存几条？超出后怎么处理？
5. 如果一个 LLM 打分返回了格式错误的 JSON（不是合法的 JSON），会发生什么？

---

## 6.9 一句话总结第六章

**M3 做三件事：算账 → 决策 → 动手。三个类各自独立，配一个熔断器防止连锁故障。三层压缩从零成本到全量 LLM，层层递进。**

---

# 第七章：M4 深度讲解——上下文选择

## 7.1 M4 解决了什么问题？

M3 解决了"对话太长时怎么压缩"的问题。但还有另一个问题：

**组装提示词时，不是所有内容都应该塞进去。**

你有 6 种内容来源（系统指令、工作区、记忆、摘要、文件缓存、对话），每种都可能很大。总共只有 10 万 token 预算，怎么分配？

M1-M3 的做法是"全部塞进去，超了再说"（事后压缩）。M4 的做法是"先选再装"（事前选择）。

---

### 术语解释：Selection（选择）

| 维度 | 说明 |
|------|------|
| 英文 | Selection |
| 中文 | 选择 / 筛选 |
| 一句话解释 | 从一堆东西里挑出重要的，剩下的不要 |
| 为什么出现 | 资源有限（token 预算），没法全部带上 |
| 本项目为什么需要 | 6 种内容来源，总共可能几十万 token，只有 10 万预算 |
| 生活例子 | 搬家打包。你有 100 箱东西，但卡车只能装 20 箱。你得挑 20 箱最重要的带上 |

---

## 7.2 M4 核心概念：Candidate（候选）

```
📁 src/context/selection/candidate.py
```

---

### 术语解释：Candidate（候选）

| 维度 | 说明 |
|------|------|
| 英文 | Candidate |
| 中文 | 候选 / 候选项 |
| 一句话解释 | 一条"我这里有这个内容"的名片，不包含实际内容 |
| 为什么出现 | 实际内容可能很大（比如文件内容 3000 行），先不加载，等确认要用再加载 |
| 本项目为什么需要 | 排序和筛选阶段只需要知道"有什么"，不需要知道"内容是什么" |
| 生活例子 | 图书馆的索书卡。卡片上只有书名、作者、位置——没有整本书的内容。等你确定要借这本书了，才去书架拿实体书 |

---

### Candidate 是一个冰冻数据类（frozen dataclass）

```python
@dataclass(frozen=True)
class Candidate:
    source: str       # 来源（如 "conversation"、"file_cache"）
    key: str          # 唯一标识（如文件路径、消息序号）
    priority: int     # 优先级（数字越大越重要）
    token_cost: int   # 预估 token 消耗
    metadata: dict    # 附加信息（给 Collector.resolve() 用）
```

**为什么是 frozen（冰冻/不可变）？** 创建后不能修改。这避免了数据在管线中被意外改动。

---

## 7.3 四阶段管线

```
📁 src/context/selection/pipeline.py
```

---

### 阶段一：Collect（收集）

```
📁 src/context/selection/collectors.py
```

6 个 Collector，各产生一批 Candidate：

```
InstructionCollector    → 1 个 Candidate（系统指令）
WorkspaceCollector      → 1 个 Candidate（工作区信息）
MemoryCollector         → N 个 Candidate（相关记忆）
SummaryCollector        → M 个 Candidate（历史摘要）
FileCacheCollector      → K 个 Candidate（缓存的文件）
ConversationCollector   → L 个 Candidate（对话轮次）
```

---

### 术语解释：Collector（收集器）

| 维度 | 说明 |
|------|------|
| 英文 | Collector |
| 中文 | 收集器 |
| 一句话解释 | 从某个来源收集可用的内容，生成 Candidate 列表 |
| 为什么出现 | 每个数据来源的"怎么收集"各不相同，需要各自实现 |
| 本项目为什么需要 | 把"收集"这个动作标准化，6 个 Collector 实现同一个接口 |
| 生活例子 | 收快递。不同快递公司（顺丰、圆通、中通）送来的包裹，统一放在门卫那里。每个快递员是一个 Collector，门卫是 SelectionPipeline |

---

### 阶段二：Rank（排序）

```
📁 src/context/selection/ranker.py
```

`PriorityRanker` 按优先级排序所有 Candidate。优先级由 `PriorityProvider` 提供：

- 系统指令：优先级最高（它是角色设定，不能丢）
- 最近的对话：优先级高于旧的对话
- 文件缓存中最近读的文件：优先级高于旧文件

---

### 术语解释：Rank（排序）

| 维度 | 说明 |
|------|------|
| 英文 | Rank |
| 中文 | 排序 / 排名 |
| 一句话解释 | 把一堆东西按重要性从高到低排列 |
| 为什么出现 | 预算是有限的，要知道哪些更重要哪些可以丢 |
| 本项目为什么需要 | 决定在 token 预算紧张时优先保留哪些内容 |
| 生活例子 | 急诊室分级。不是先来先看，而是按病情严重程度排：心脏骤停 > 骨折 > 感冒 |

---

### 阶段三：Select（选择）

```
📁 src/context/selection/policy.py
```

`BudgetSelectionPolicy` 根据 `TokenConstraint` 裁剪 Candidate：

```python
TokenConstraint(source="instruction", max_tokens=10000, reserved=True)
TokenConstraint(source="conversation", max_tokens=60000, reserved=False)
```

- `reserved=True`：就算超预算也必须保留（系统指令必须带上）
- `reserved=False`：超预算就丢弃（对话轮次太多时，旧的被丢）

**关键设计：选择是基于"累积 token 消耗"的。**

```
遍历排序后的 Candidate：
  if 当前候选的 token_cost + 累积消耗 <= 该来源的 max_tokens:
    选中 ✅
    累积消耗 += token_cost
  else:
    if 该来源是 reserved:
      仍然选中 ✅（但记录"超预算"）
    else:
      丢弃 ❌
```

---

### 术语解释：Constraint（约束）

| 维度 | 说明 |
|------|------|
| 英文 | Constraint |
| 中文 | 约束 / 限制 |
| 一句话解释 | 一个硬性条件，"不能超过" |
| 为什么出现 | 预算是硬的，不是建议，是必须遵守的 |
| 本项目为什么需要 | `TokenConstraint` 对每种来源设 token 上限 |
| 生活例子 | 电梯载重 1000 公斤。超过就报警、不开门。这就是一个约束 |

---

### 阶段四：Pack（打包）

```
📁 src/context/selection/packer.py
```

此时已确定了"哪些 Candidate 入选"。`Packer` 调用每个已选 Candidate 对应的 `Collector.resolve()` 方法，**真正加载内容**。

输出：`PromptPackage`——一个结构化的、准备好给 `PromptBuilder` 使用的数据包。

```python
PromptPackage {
    system_blocks: ["你是一个编程助手...", "当前目录: D:/s_full"],
    message_blocks: [{"role": "user", "content": "..."}, ...],
    stats: SelectionStats { collected: 45, selected: 28, discarded: 17 }
}
```

---

## 7.4 M4 完整流程图

```
SelectionPipeline.run(ctx)
    │
    ├── Phase 1: Collect
    │   6 个 Collector 各自产生 Candidate
    │   每个 Candidate 只是"名片"，不含实际内容
    │
    ├── Phase 2: Rank
    │   PriorityRanker 按优先级排序所有 Candidate
    │   输出：有序的 Candidate 列表
    │
    ├── Phase 3: Select
    │   BudgetSelectionPolicy 按 TokenConstraint 裁剪
    │   reserved=True → 必须保留
    │   reserved=False → 超了就丢
    │   输出：(选中的, 丢弃的)
    │
    └── Phase 4: Pack
        Packer 调用 Collector.resolve() 加载实际内容
        输出：PromptPackage
              │
              ▼
        PromptBuilder.build_from_package(package)
              │
              ▼
        发给大模型的最终提示词
```

---

## 7.5 思考题

1. 为什么 Candidate 要设计成 frozen（不可变）？如果可变会有什么问题？
2. 为什么 Collector.resolve() 要放在 Pack 阶段而不是 Collect 阶段？
3. 如果 `reserved=True` 的来源本身就超过了总预算，系统会怎样？
4. `PriorityProvider` 是可替换的。如果我想让"包含特定关键词的文件"优先级更高，我应该改哪个类？
5. 如果去掉整个 M4 选择管线，系统还能工作吗？会有什么变化？

---

## 7.6 一句话总结第七章

**M4 做四件事：先收集所有"我有这个"的名片 → 按重要性排序 → 按预算裁剪 → 最后才加载实际内容。把"选内容"和"装内容"分开。**

---

# 第八章：M5 深度讲解——可观测与恢复

## 8.1 M5 解决了什么问题？

M1-M4 让系统可以正常运行。但工程级的系统还需要回答这些问题：

1. **系统崩溃了怎么办？** 能不能恢复到上次的状态？
2. **上次压缩用了多少 token？** 有没有记录？
3. **为什么那次选择丢掉了我的对话？** 能不能回溯？
4. **整个系统的健康状况如何？** 有没有一个仪表盘？
5. **如果我想看"3 轮之前发给 LLM 的提示词长什么样"？** 能不能回放？

M5 就是回答这些问题的。

---

## 8.2 M5 包含什么

| 组件 | 作用 | 文件 |
|------|------|------|
| `Serializer` | 把对象转成可存储的字典，反之亦然 | `src/context/serialization/` |
| `RecoveryEngine` | 保存和恢复系统状态 | `src/context/recovery/recovery.py` |
| `AuditLog` | 操作审计日志（谁在什么时候做了什么） | `src/context/observability/audit.py` |
| `DashboardBuilder` | 健康仪表盘（token 分布、压缩统计） | `src/context/observability/dashboard.py` |
| `ExecutionTrace` | 单次执行的完整追踪 | `src/context/observability/trace.py` |
| `ReplayEngine` | 回放历史提示词 | `src/context/replay/replay.py` |

---

## 8.3 Serializer（序列化器）

```
📁 src/context/serialization/serializer.py
```

---

### 术语解释：Serialization（序列化）

| 维度 | 说明 |
|------|------|
| 英文 | Serialization |
| 中文 | 序列化 |
| 一句话解释 | 把一个内存对象变成可以存盘、可以传输的格式（反过来叫反序列化） |
| 为什么出现 | Python 对象存在内存里，程序关了就没。要保存就必须转成 JSON/文件 |
| 本项目为什么需要 | 压缩结果、选择结果、Dashboard 快照都需要存盘 |
| 生活例子 | 搬家时把家具拆成零件（序列化），搬到新家再组装起来（反序列化） |

---

本项目序列化器支持 10 种类型，每种都有 `to_dict()`（对象 → 字典）和 `from_dict()`（字典 → 对象）。

```python
# 序列化（对象 → 字典）
data = serialize(candidate)
# → {"_schema": "1.0", "_type": "candidate", "source": "conversation", ...}

# 反序列化（字典 → 对象）
candidate = deserialize(data)
# → Candidate(source="conversation", ...)
```

---

## 8.4 RecoveryEngine（恢复引擎）

```
📁 src/context/recovery/recovery.py
```

---

### 术语解释：Recovery（恢复）

| 维度 | 说明 |
|------|------|
| 英文 | Recovery |
| 中文 | 恢复 |
| 一句话解释 | 从之前保存的状态恢复，程序崩了以后能接着之前的进度继续 |
| 为什么出现 | 程序不是永远不崩的。用户关终端、服务器重启、网络断开... |
| 本项目为什么需要 | 保存当前对话的总结状态、工作区状态、会话元数据，重启后恢复 |
| 生活例子 | 游戏存档。你打了 3 小时的 BOSS 战，突然停电了。如果有存档，明天可以接着打。没有存档，从第一关重新来 |

---

### 它保存什么？

```python
RecoveryEngine.save()  # 保存到 Store
  ├── SummaryState:   压缩后的历史摘要
  ├── WorkspaceState: 当前工作目录、git 分支
  └── SessionState:   会话元数据（开始时间、消息数等）

RecoveryEngine.load()  # 从 Store 恢复
  ├── 恢复 SummaryState → SummaryLayer
  ├── 恢复 WorkspaceState → WorkspaceLayer
  └── 恢复 SessionState → 显示恢复信息
```

### 迁移系统

```
📁 src/context/recovery/migration.py
```

如果以后改了存储格式（schema 版本从 1.0 变 2.0），旧数据怎么办？

迁移系统用 BFS（广度优先搜索）找从旧版本到新版本的最短迁移路径。每个版本之间的迁移是一个函数，BFS 自动找到最短的路径链。

---

## 8.5 AuditLog（审计日志）

```
📁 src/context/observability/audit.py
```

---

### 术语解释：Audit（审计）

| 维度 | 说明 |
|------|------|
| 英文 | Audit |
| 中文 | 审计 |
| 一句话解释 | 记录"谁在什么时候做了什么"，用于事后追查 |
| 为什么出现 | 出了问题需要回溯。不知道历史就没法排查 |
| 本项目为什么需要 | 记录关键操作（压缩、选择、恢复），出问题时可以回溯 |
| 生活例子 | 飞机黑匣子。飞机出事后，调查员靠黑匣子还原驾驶舱里每句话、每个操作 |

---

审计日志是一个环形缓冲区（ring buffer），最多保留 200 条记录。新记录会覆盖最旧的记录。

```python
audit_log.record(event="compression_executed", detail={...})
# 写入: {"timestamp": 1719300000, "event": "compression_executed", ...}
```

---

## 8.6 Dashboard（仪表盘）

```
📁 src/context/observability/dashboard.py
```

---

### 术语解释：Dashboard（仪表盘）

| 维度 | 说明 |
|------|------|
| 英文 | Dashboard |
| 中文 | 仪表盘 |
| 一句话解释 | 一张图看所有关键指标：token 用了多少、压缩了多少次、选择了哪些内容 |
| 为什么出现 | 运维需要快速了解系统状态，不能每次都翻日志 |
| 本项目为什么需要 | 提供一次请求的完整快照，包括 token 分布、选择结果、压缩耗时 |
| 生活例子 | 汽车仪表盘。速度、油量、水温、里程全在一个地方，不用逐个检查 |

---

`DashboardSnapshot` 包含：

```
TokenBreakdown:     每种内容的 token 消耗
SelectionBreakdown: 选择了多少、丢弃了多少
CompressionBreakdown: 每层压缩的耗时和效果
LatencyBreakdown:   每阶段的耗时
```

---

## 8.7 M5 数据流

```
每次 agent_loop 循环
       │
       ├── tick() 压缩
       │   ├── PipelineResult → ExecutionTrace 记录
       │   └── AuditLog.record("compression_executed")
       │
       ├── build_prompt() 组装
       │   ├── SelectionResult → ExecutionTrace 记录
       │   └── AuditLog.record("prompt_built")
       │
       └── DashboardBuilder.build(trace, budget_report, selection_result)
           └── DashboardSnapshot → 可选存盘
```

---

## 8.8 思考题

1. 如果 RecoveryEngine 保存状态的时机不对（比如在压缩途中保存），会发生什么？
2. AuditLog 的环形缓冲区满了之后，最旧的记录被覆盖。哪些记录是绝对不能丢的？
3. DashboardSnapshot 是每次请求都存一份，还是只保留最新的？各有什么利弊？
4. 如果 Schema 版本从 1.0 升级到 2.0，但 BFS 找不到迁移路径，会发生什么？

---

## 8.9 一句话总结第八章

**M5 是 Context Engine 的"后勤保障"——序列化让数据能存盘、恢复让系统能续命、审计让你能回溯、仪表盘让你能监控、回放让你能复盘。**

---

# 第九章：main.py 逐行分析

## 9.1 main.py 的职责全景

`main.py` 是整个项目的"接线板"。它不实现任何核心逻辑，只做一件事：**把各个模块初始化好、连起来、启动。**

## 9.2 按区域分析

### 区域一：启动引导（第 1-28 行）

```python
load_dotenv(override=True)
client = Anthropic(base_url=...)
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-6-20250514")
```

**为什么放在最前面？**
- 环境变量（API 密钥、模型名称）是后面所有操作的前提
- `load_dotenv(override=True)` 确保从 `.env` 文件读的配置优先于系统环境变量

---

### 区域二：导入（第 30-76 行）

**为什么这么多 import？**
- 每个模块独立写在一个文件/目录里
- main.py 需要把所有模块"认识"一遍才能组装
- 这不是设计缺陷，是模块化架构的特点

**为什么不用 `import *`？**
- 显式导入让你一眼能看到谁依赖谁
- 代码跳转（Ctrl+点击）可以直接跳到来源

---

### 区域三：全局单例（第 90-115 行）

```python
TODO = TodoManager()
SKILLS = SkillLoader(WORKDIR / "skills")
TASK_MGR = TaskManager(WORKDIR / ".tasks")
BUS = MessageBus(WORKDIR)
SCRATCHPAD = Scratchpad()
STORE = Store({"cwd": str(WORKDIR), "model": MODEL})
SESSION = SessionState(WORKDIR)
```

---

### 术语解释：Singleton（单例）

| 维度 | 说明 |
|------|------|
| 英文 | Singleton |
| 中文 | 单例 |
| 一句话解释 | 全局只有一个实例，所有代码共用同一个对象 |
| 为什么出现 | 有些对象（比如消息总线、任务管理器）必须全局共享，不能各自创建各自的 |
| 本项目为什么需要 | `STORE` 是全局键值存储，如果每个模块各创建一个 Store，数据就不同步了 |
| 生活例子 | 公司的饮水机。全公司只有一台，所有人共用。不会有人自己买一台放工位下面 |

---

### 区域四：工具注册（第 132-224 行）

每个 `build_tool(...)` 定义了一个可被大模型调用的工具。注册到 `registry` 后，大模型就能看到这些工具并选择调用。

**为什么在 main.py 里注册而不是在各自模块里？**
- 集中管理，一眼能看到全部可用工具
- 工具的定义（名称、描述、参数格式）和实现分离

---

### 区域五：Memory OS 初始化（第 328-370 行）

```python
memory_core = MemoryCore(db_path=WORKDIR / ".memory")  # M6
retrieval_engine = memory_core.init_retrieval()          # M7
importance_engine = memory_core.init_importance()        # M8
intelligence_engine = memory_core.init_intelligence()    # M9
lifecycle_engine = memory_core.init_lifecycle()          # M10
```

**为什么是链式初始化？**
- M7 依赖 M6（需要 store）
- M8 依赖 M7（需要检索结果来追踪访问）
- M9 依赖 M7+M8（需要向量索引 + 重要性引擎）
- M10 依赖 M7（需要向量索引来做压缩分组）

这个依赖链不能乱。

---

### 区域六：Context Engine 组装（第 372-470 行）

这是整个文件最复杂的部分。逐层看：

```python
# M2
workspace = WorkspaceLayer(cwd=str(WORKDIR))
file_cache = FileCacheLayer(max_files=20, max_lines=150)

# M3: Budget
budget_mgr = BudgetManager(...)

# M3: Compression
compress_policy = CompressionPolicy()
compress_policy.add_rule(OverBudgetRule(...))
compress_pipeline = CompressionPipeline(stages=[...])
circuit_breaker = CircuitBreaker(max_failures=3, reset_timeout=60.0)

# M4: Selection
selection_pipeline = SelectionPipeline(
    collectors=[...6 个 Collector...],
    rankers=[PriorityRanker()],
    policy=BudgetSelectionPolicy([...6 个 TokenConstraint...]),
)

# M5
recovery = RecoveryEngine(store=STORE)
audit_log = AuditLog(store=STORE, max_entries=200)

# 组装总调度器
orchestrator = ContextOrchestrator(
    store=STORE,
    base_system=SYSTEM,
    budget=budget_cfg,
    workspace=workspace,
    file_cache=file_cache,
    memory_layer=memory_layer,
    budget_manager=budget_mgr,
    compression_policy=compress_policy,
    compression_pipeline=compress_pipeline,
    summarizer=summarizer,
    llm_call=_compress_llm,
    circuit_breaker=circuit_breaker,
    selection_pipeline=selection_pipeline,
)
```

---

### 术语解释：Dependency Injection（依赖注入）

| 维度 | 说明 |
|------|------|
| 英文 | Dependency Injection |
| 中文 | 依赖注入 |
| 一句话解释 | 一个类不自己创建它需要的东西，而是通过构造函数从外面"注入" |
| 为什么出现 | 让类"只知道接口，不关心实现"。测试时可以注入假的实现 |
| 本项目为什么需要 | `ContextOrchestrator` 不自己创建 `BudgetManager`、`CompressionPipeline` 等，而是通过 `__init__` 接收。这样你可以替换任何一个组件 |
| 生活例子 | 手机不内置一个固定的充电器，而是给你一个 USB-C 口（接口）。你可以插小米充电器、华为充电器、苹果充电器。你"注入"了哪个充电器，手机就用哪个 |

---

### 区域七：REPL 循环（第 480+ 行）

无限循环读取用户输入，每轮：
1. 检查是否是 REPL 命令（`/compact`、`/tasks`、`/memory` 等）
2. 执行钩子
3. `orchestrator.add_message("user", query)`
4. `agent_loop(..., orchestrator=orchestrator)`
5. 打印结果

---

## 9.3 为什么 old 模式和 new 模式并存？

在 `agent_loop` 里有两条路径：

```python
if orchestrator is not None:
    # 新路径：全部走 Context Engine
    messages = orchestrator.get_messages()
    orchestrator.tick()
    orchestrator.build_prompt()
else:
    # 旧路径：直接操作 messages 列表
    _build_system_prompt()
    microcompact()
```

**为什么保留旧路径？**
- 兼容性：万一 Context Engine 出问题，可以切回旧模式
- 但这是技术债，应该尽快去掉。本项目的 main.py 传了 `orchestrator`，所以只走新路径

---

## 9.4 思考题

1. 如果把 `circuit_breaker` 的 `max_failures` 从 3 改成 1，会有什么影响？
2. 为什么 `TokenConstraint` 的 `reserved` 属性要在这里设置，而不是在 `SelectionPipeline` 内部硬编码？
3. `_compress_llm` 函数为什么定义在 main.py 而不是 compression 模块里？放在哪更合适？

---

## 9.5 一句话总结第九章

**main.py 是接线员——不干业务，只负责把每个模块初始化好、连起来、启动。**

---

# 第十章：所有重要类之间的关系

## 10.1 拥有关系（谁创建了谁）

```
main.py
  ├── 创建 → Store (全局键值存储)
  ├── 创建 → MemoryCore (记忆系统入口)
  │   ├── 创建 → MemoryStore (记忆存储)
  │   ├── 创建 → MemoryPipeline (记忆写入管线)
  │   ├── 创建 → RetrievalEngine (M7, 按需)
  │   ├── 创建 → ImportanceEngine (M8, 按需)
  │   ├── 创建 → IntelligenceEngine (M9, 按需)
  │   └── 创建 → LifecycleEngine (M10, 按需)
  ├── 创建 → WorkspaceLayer (工作区感知)
  ├── 创建 → FileCacheLayer (文件缓存)
  ├── 创建 → BudgetManager (算账)
  ├── 创建 → CompressionPolicy (做决定)
  ├── 创建 → CompressionPipeline (动手)
  │   ├── MicroCompactStage
  │   ├── ContextCollapseStage
  │   └── AutoCompactStage
  ├── 创建 → SelectionPipeline (选择)
  │   ├── 6 个 Collector
  │   ├── PriorityRanker
  │   └── BudgetSelectionPolicy
  ├── 创建 → RecoveryEngine (恢复)
  ├── 创建 → AuditLog (审计)
  └── 组装 → ContextOrchestrator (总调度器)
      ├── 持有 → 所有 Layer
      ├── 持有 → BudgetManager
      ├── 持有 → CompressionPolicy + Pipeline
      ├── 持有 → SelectionPipeline
      └── 持有 → PromptBuilder
```

## 10.2 调用关系（谁调用了谁）

```
agent_loop()
  ├── orchestrator.tick()
  │   ├── BudgetManager.check(layers)
  │   ├── CompressionPolicy.evaluate(reports)
  │   └── CompressionPipeline.execute(plan)
  ├── orchestrator.build_prompt()
  │   ├── SelectionPipeline.run(ctx)
  │   │   ├── Collector.collect(ctx)    [×6]
  │   │   ├── Ranker.rank(candidates)
  │   │   ├── Policy.select(candidates)
  │   │   └── Packer.pack(selected, collectors)
  │   └── PromptBuilder.build_from_package(package)
  └── orchestrator.add_message(role, content)
      └── ConversationLayer.add(message)
```

## 10.3 生命周期

| 对象 | 创建时机 | 销毁时机 | 存活时间 |
|------|---------|---------|---------|
| `Store` | main.py 启动 | 进程退出 | 整个进程 |
| `ContextOrchestrator` | main.py 组装 | 进程退出 | 整个进程 |
| `BudgetReport` | 每次 `tick()` | 函数返回 | 一次调用 |
| `CompressionPlan` | 每次 `evaluate()` | 函数返回 | 一次调用 |
| `Candidate` | 每次 Collect | Pipeline 返回后 | 一次选择 |
| `PromptPackage` | 每次 Pack | Builder 返回后 | 一次组装 |
| `DashboardSnapshot` | 可选 | 进程退出或手动清理 | 按需 |

---

# 第十一章：代码阅读路线

## 新手 5 天学习路线

### Day 1：骨架

**上午**（1-2 小时）：
1. 打开 `main.py`，从第 1 行读到第 110 行
2. 关注：import 了什么、创建了什么全局对象
3. 跳过：内部实现细节，只看名字

**下午**（1-2 小时）：
1. 打开 `src/context/orchestrator.py`
2. 关注：`__init__` 的参数、`tick()`、`build_prompt()`、`add_message()` 四个方法
3. 不用关心内部实现，只看"它提供了哪些方法"

**重点理解**：Orchestrator 是总入口，所有上下文操作都通过它。

---

### Day 2：压缩

**上午**（1-2 小时）：
1. 打开 `src/context/budget/manager.py`
2. 关注：`check()` 方法如何计算每层的 token 消耗
3. 打开 `src/context/compression/policy.py`
4. 关注：`evaluate()` 方法如何匹配规则

**下午**（1-2 小时）：
1. 打开 `src/context/compression/stages.py`
2. 逐个看三个 Stage 的 `run()` 方法
3. 打开 `src/context/compression/circuit_breaker.py`
4. 画一遍三态状态转换图

**重点理解**：算账 → 决策 → 动手 → 熔断，四步走。

---

### Day 3：选择

**上午**（1-2 小时）：
1. 打开 `src/context/selection/candidate.py`，理解 Candidate 为什么是 frozen
2. 打开 `src/context/selection/collectors.py`，看 6 个 Collector 各产生什么
3. 打开 `src/context/selection/ranker.py`，看排序逻辑

**下午**（1-2 小时）：
1. 打开 `src/context/selection/policy.py`
2. 打开 `src/context/selection/packer.py`
3. 打开 `src/context/selection/pipeline.py`
4. 串联：Collect → Rank → Select → Pack

**重点理解**：为什么内容在 Pack 阶段才加载，不是在 Collect 阶段。

---

### Day 4：可观测

**上午**（1-2 小时）：
1. 打开 `src/context/serialization/serializer.py`
2. 打开 `src/context/recovery/recovery.py`
3. 理解 `save()` 和 `load()` 的对应关系

**下午**（1-2 小时）：
1. 打开 `src/context/observability/audit.py`
2. 打开 `src/context/observability/dashboard.py`
3. 打开 `src/context/replay/replay.py`

**重点理解**：恢复和审计是生产系统必须有但初学者最容易忽略的。

---

### Day 5：串联

**上午**（2-3 小时）：
重新打开 `main.py`，找到 `main()` 函数（约第 320 行开始），逐行阅读：
- 每个对象为什么在这里初始化？
- 为什么是这个顺序？
- 哪个对象注入了哪个对象？

**下午**（2-3 小时）：
在纸上画一张完整的系统数据流图。从 `main.py` → `orchestrator.tick()` → `orchestrator.build_prompt()` → LLM API。

**重点理解**：所有模块是如何协同工作的。

---

## 11.2 哪些可以先跳过

- `detector.py`：项目检测工具，核心逻辑不在这里
- `replay/diff.py`：快照对比，属于高级功能
- `serialization/schema.py`：信封格式定义，不影响理解核心逻辑

---

# 第十二章：系统完整数据流

## 12.1 最大流程图

```
用户输入 "帮我找一个bug"
         │
         ▼
    main.py REPL 循环
         │
         ├── 检查是否是命令 (/compact, /tasks...)
         │
         ▼
    UserPromptSubmit 钩子
         │
         ├── 拦截？→ 返回 "blocked"
         │
         ▼
    orchestrator.add_message("user", query)
         │
         ▼
    agent_loop(history, registry, client, ..., orchestrator=orchestrator)
         │
         ▼
    ┌─────────────────────────────────────────────────────┐
    │              每次循环开始                            │
    │                                                      │
    │  ① orchestrator.tick()                              │
    │     ├── BudgetManager.check(layers)                  │
    │     │   → "对话层用了 85000/90000 token"             │
    │     ├── CompressionPolicy.evaluate(reports)           │
    │     │   → "连续 2 次超预算，执行最多 T3，目标 50%"   │
    │     └── CompressionPipeline.execute(plan)            │
    │         ├── MicroCompactStage (清除旧 tool_result)   │
    │         ├── ContextCollapseStage (LLM 打分+摘要)     │
    │         │   └── 重要事件 → on_important → Store      │
    │         └── AutoCompactStage (全量 LLM 摘要)         │
    │             └── 摘要 → SummaryLayer                  │
    │                                                      │
    │  ② 后台消息 + 通知排空                               │
    │     ├── BG.drain() → 后台任务完成通知                │
    │     └── BUS.read_inbox("lead") → 其他 Agent 消息     │
    │                                                      │
    │  ③ orchestrator.build_prompt()                      │
    │     └── SelectionPipeline.run(ctx)                   │
    │         ├── Collect (6 个 Collector)                 │
    │         ├── Rank (PriorityRanker)                    │
    │         ├── Select (BudgetSelectionPolicy)           │
    │         └── Pack (加载实际内容 → PromptPackage)      │
    │     └── PromptBuilder.build_from_package(package)    │
    │         → {system: "...", messages: [...]}           │
    │                                                      │
    │  ④ 意图分类 + 工具过滤                               │
    │     └── INTENT_CLASSIFIER.classify(last_user_msg)    │
    │     └── filter_by_intent(intent, all_tools)          │
    │                                                      │
    │  ⑤ LLM API 调用                                     │
    │     └── client.messages.create(                      │
    │           messages=messages,                         │
    │           system=system_prompt,                      │
    │           tools=filtered_tools                       │
    │         )                                            │
    │                                                      │
    │  ⑥ 处理响应                                         │
    │     ├── 纯文本回复 → Stop 钩子 → 循环结束            │
    │     └── 工具调用 →                                   │
    │         ├── PreToolUse 钩子 (可拦截/修改)            │
    │         ├── registry.execute(name, **input)          │
    │         │   └── M2 事件: on_file_read / on_file_write│
    │         ├── PostToolUse 钩子                         │
    │         └── 结果追加到 messages → 回到 ①            │
    └─────────────────────────────────────────────────────┘
         │
         ▼
    循环结束
         │
         ▼
    打印结果给用户
         │
         ▼
    RecoveryEngine.save()  ←── 自动保存状态
```

---

## 12.2 一句话总结第十二章

**从用户输入到 LLM 回复，经历了：钩子检查 → 压缩（算账→决策→动手）→ 选择（收集→排序→筛选→打包）→ 组装提示词 → 调 LLM → 执行工具 → 重复直到完成。**

---

# 术语词典（Glossary）

| 英文 | 中文 | 一句话解释 | 生活例子 | 在本项目里的作用 |
|------|------|-----------|---------|----------------|
| Audit | 审计 | 记录谁在什么时候做了什么 | 飞机黑匣子 | `AuditLog` 记录关键操作可回溯 |
| Budget | 预算 | 分配资源的上限 | 旅游预算 | `BudgetManager` 按比例分配 token |
| Builder | 组装器 | 把零件拼成成品 | 宜家安装说明书 | `PromptBuilder` 拼装最终提示词 |
| Cache | 缓存 | 临时存储常用数据 | 手机最近联系人 | `FileCacheLayer` 缓存最近读的文件 |
| Candidate | 候选 | 一张"我有这个内容"的名片 | 图书馆索书卡 | 选择管线的基本单位，不含实际内容 |
| Circuit Breaker | 熔断器 | 连续失败就跳过，过会再试 | 家里电闸跳闸 | 防止 LLM 失败时反复重试浪费资源 |
| Collector | 收集器 | 从某个来源收集信息 | 收快递的快递员 | 6 个 Collector 从不同来源产生 Candidate |
| Compression | 压缩 | 把大量内容精简成少量 | 把一本书整理成读书笔记 | 三层压缩管线精简对话历史 |
| Constraint | 约束 | 一个硬性限制条件 | 电梯限载 1000kg | `TokenConstraint` 限制每种来源的 token 上限 |
| Context | 上下文 | 让 AI 理解"现在是什么情况"的信息 | 医生看病历+问诊 | Context Engine 统一管理所有上下文 |
| Dependency Injection | 依赖注入 | 从外面传进来，不是自己创建 | 手机 USB-C 口可插不同充电器 | `Orchestrator` 通过构造函数接收所有组件 |
| Event-Driven | 事件驱动 | 有变化了通知我，不是我一直问 | 快递到了发短信 | M2 用事件通知 orchestrator 更新文件缓存 |
| Hook | 钩子 | 在关键节点自动执行的函数 | 出门前检查钥匙手机钱包 | 5 种钩子在用户说话/工具执行前后触发 |
| Layer | 层 | 一层一层的馅料，各管各的 | 汉堡的面包/肉饼/生菜层 | 6 种 Layer 各存不同类型的上下文 |
| LRU | 最近最少使用 | 空间不够时踢掉最久没用的 | 扔冰箱最久的剩菜 | FileCacheLayer 的缓存淘汰策略 |
| Orchestrator | 调度器 | 乐队总指挥 | 拍电影的导演 | Context Engine 的唯一入口 |
| Pipeline | 流水线 | 一步一步加工，每步做一件事 | 奶茶店：点单→做茶→封口 | 压缩和选择都是 Pipeline 模式 |
| Policy | 策略 | "如果...就..."的规则 | 公司报销政策 | `CompressionPolicy` 决定何时触发压缩 |
| Prompt | 提示词 | 发给大模型的文字 | 餐厅点菜说的需求 | Context Engine 最终组装的就是 Prompt |
| Rank | 排序 | 按重要性从高到低排 | 急诊室按病情分级 | `PriorityRanker` 决定哪些 Candidate 优先保留 |
| Recovery | 恢复 | 从存档恢复之前的状态 | 游戏读档接着打 | `RecoveryEngine` 保存/恢复 SummaryState 等 |
| Selection | 选择 | 从一堆里挑出重要的 | 搬家时挑 20 箱重要的带上卡车 | M4 选择管线决定哪些内容进提示词 |
| Serialization | 序列化 | 对象转成可存储的格式 | 搬家时把家具拆成零件 | `Serializer` 支持 10 种类型的序列化/反序列化 |
| Singleton | 单例 | 全局只有一个实例 | 公司饮水机 | `STORE`、`BUS` 等全局只有一个 |
| Stage | 阶段 | Pipeline 中的一个步骤 | 洗车：预洗→泡沫→冲洗→擦干 | 三层压缩各自是一个 Stage |
| Token | 词元 | 大模型计费的基本单位 | 发短信按"条"收费 | 控制上下文大小的核心指标 |
| Workspace | 工作区 | 项目目录+git 等环境信息 | VS Code 左下角显示的路径 | `WorkspaceLayer` 让 AI 感知当前工作环境 |

---

> **文档版本**：v1.0  
> **覆盖范围**：Context Engine M1-M5  
> **总字数**：约 50,000 中文字  
> **建议阅读方式**：每天一章，配合代码打开对照阅读
