# Memory OS 从零到精通（开发者教材）

> 这不是 API 文档，不是代码注释，也不是项目 README。  
> 这是一本教材，目标是让一个只有 Python 基础的人，彻底理解整个 Memory OS。

---

## 阅读前说明

**你需要的基础**
- 会 Python 基础语法（class、def、if、for、列表、字典）
- 理解 Context Engine 的基本概念（层、预算、选择管线）
- 能在命令行运行 `python main.py`

**你不需要的基础**
- 不需要懂任何数据库引擎
- 不需要懂向量检索
- 不需要懂机器学习

**本文的约定**
- 每个英文术语第一次出现时，都会按照下面的格式解释：
  1. 英文原文
  2. 中文翻译
  3. 一句话解释
  4. 为什么会出现这个概念
  5. 本项目为什么需要它
  6. 在本项目中负责什么
  7. 一个生活中的例子

**代码定位格式**
- 每个类都会标注：`📁 文件路径` + `📍 类定义行号`

---

# 第一章：为什么会有 Memory OS？

## 1.1 从一个真实问题开始

你跟 AI 编程助手说：

> "帮我给这个项目加一个用户认证系统。"

AI 开始工作。它读了你的项目文件，创建了 `auth.py`，配置了 JWT，一切正常。

**第二天**，你又说：

> "帮我给认证系统加上刷新 token 的功能。"

问题来了：AI 还记得昨天做了什么吗？

没有 Memory 系统的情况下，答案是：**不记得**。

每次你跟大模型对话，它都是从零开始的。它不记得昨天创建了 `auth.py`，不记得你选择了 JWT 而不是 Session，不记得你说过"不要用 OAuth，太复杂了"。

这就是 Memory OS 要解决的核心问题。

---

### 术语解释：Memory（记忆）

| 维度 | 说明 |
|------|------|
| 英文 | Memory |
| 中文 | 记忆 / 持久化知识 |
| 一句话解释 | 让 AI 记住上次对话结束后的重要信息，下次对话还能用 |
| 为什么出现 | 大模型没有长期记忆。每次调用 API 都是独立的，不知道之前发生过什么 |
| 本项目为什么需要 | Agent 需要在多次对话之间记住：用户偏好、项目决策、踩过的坑、常用的工具 |
| 在本项目中负责 | 由 Memory OS 统一管理，提供 CRUD、检索、自动学习、生命周期管理 |
| 生活例子 | 你去看同一个医生复诊。上次的诊断记录、过敏史、开的药方都在病历里。病历就是医生的"长期记忆" |

---

## 1.2 传统做法：存数据库

最简单的做法：搞一个 SQLite 或 JSON 文件，把重要信息存起来。

看起来很简单对吧？但问题来了：

**问题一：存什么、什么时候存？**

你不能让用户手动管理记忆——"现在请你点击'保存记忆'按钮"。记忆应该是自动的。

**问题二：怎么找到相关的记忆？**

当 AI 在处理认证问题时，不应该去检索关于"CSS 样式"的记忆。你需要智能检索。

**问题三：记忆会越来越多**

存了 1000 条记忆后，哪些还有用？哪些已经过时了？谁来清理？

**问题四：记忆之间有冲突**

第一天你说"用 JWT"，第二天你说"换成 Session 吧"。两条记忆互相矛盾，怎么处理？

---

## 1.3 解决思路：企业级记忆内核

Memory OS 用五个里程碑（M6-M10）解决上面的问题：

**M6 Memory Core**：提供最基础的存储能力——增删改查、分类、索引、校验。像一个"带标签的文件柜"。

**M7 Retrieval Engine**：让记忆可以被智能检索——关键词 + 语义 + 最近，三通道混合检索。不止是"找标签"，还能"找意思相近的"。

**M8 Importance Engine**：让记忆有"价值分数"——重要的记忆浮上来，过时的沉下去。自动评分、衰减、反馈学习。

**M9 Intelligence Engine**：让记忆能"自动学习"——从对话中自动提取知识，检测冲突，合并相似记忆。

**M10 Lifecycle Engine**：让记忆能"自我管理"——自动归档、压缩、垃圾回收，保持记忆库健康。

---

## 1.4 一句话总结第一章

**Memory OS 解决的核心问题是：让 AI 在多次对话之间保持"记忆"，并且能智能地检索、更新、清理这些记忆。**

---

# 第二章：Memory OS 总体架构

## 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户 / Agent                             │
│                            │                                    │
│                    memory_add / memory_search                   │
│                            │                                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MemoryCore（总门面）                        │
│  所有模块的统一入口。外部代码只跟它说话。                         │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  M6: Memory Core（10 子系统）                          │     │
│  │                                                        │     │
│  │  ┌────────┐ ┌────────┐ ┌──────────┐ ┌─────────────┐  │     │
│  │  │ Store  │ │Pipeline│ │ Policy   │ │ Lifecycle   │  │     │
│  │  │ 纯存储 │ │写前处理│ │ 规则引擎 │ │ 状态转移    │  │     │
│  │  └────────┘ └────────┘ └──────────┘ └─────────────┘  │     │
│  │  ┌────────┐ ┌────────┐ ┌──────────┐ ┌─────────────┐  │     │
│  │  │ Events │ │ Index  │ │ Registry │ │ Metadata    │  │     │
│  │  │ 事件总线│ │ 倒排索引│ │ 类型注册 │ │ 扩展存储    │  │     │
│  │  └────────┘ └────────┘ └──────────┘ └─────────────┘  │     │
│  │  ┌────────┐ ┌────────┐                               │     │
│  │  │ Schema │ │Identity│                               │     │
│  │  │ 校验迁移│ │ ID类型  │                               │     │
│  │  └────────┘ └────────┘                               │     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  M7: Retrieval Engine（检索引擎）                      │     │
│  │  Planner → Keyword + Vector + Recent → Hybrid → Rerank│     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  M8: Importance Engine（重要性引擎）                    │     │
│  │  Scorer + Decay + Tracker + Feedback + Vacuum          │     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  M9: Intelligence Engine（智能引擎）                    │     │
│  │  Trigger → Extract → Validate → Reflect (Merge/Split)  │     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  M10: Lifecycle Engine（生命周期引擎）                  │     │
│  │  Archive + Compress + GC + Metrics                     │     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  Context OS 桥接：MemoryLayer + MemoryCollector        │     │
│  │  让记忆自动出现在发给大模型的上下文中                    │     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  Agent Tools：16 个工具供 Agent 直接调用                │     │
│  │  add / get / search / update / delete / feedback ...   │     │
│  └───────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                    持久化到 disk (JSON)
```

## 2.2 五个里程碑总览

| 里程碑 | 名字 | 一句话解释 | 文件位置 |
|--------|------|-----------|----------|
| M6 | 记忆内核 | 10 子系统的存储与处理基础 | `src/memory/` 根目录 14 个文件 |
| M7 | 检索引擎 | 三通道混合检索 + 异步 Embedding | `src/memory/retrieval/` |
| M8 | 重要性引擎 | 动态评分、衰减、反馈学习 | `src/memory/importance/` |
| M9 | 智能引擎 | 自动从对话提取知识、检测冲突 | `src/memory/intelligence/` |
| M10 | 生命周期引擎 | 自动归档、压缩、垃圾回收 | `src/memory/lifecycle/` |

---

## 2.3 核心设计原则

**原则一：一个门面（Facade）**

所有外部代码都和 `MemoryCore` 对话，不直接操作 `MemoryStore`、`MemoryPipeline` 等内部组件。你只需要记住一个入口。

**原则二：事件驱动（Event-Driven）**

所有变更（创建、更新、删除、归档）都通过 `MemoryEventBus` 发射事件。M7 的 Embedding Worker、M8 的 Access Tracker、M9 的 Trigger Policy 都是事件订阅者。新功能只需订阅事件，不改旧代码。

**原则三：管道处理（Pipeline）**

所有写入都要经过 Pipeline：Schema 校验 → Normalize 规范化 → Deduplicate 去重 → PolicyCheck 规则检查 → Persist 持久化。五道关卡，拒绝脏数据。

**原则四：不修改旧代码**

M7 不改 M6 一行代码。M8 不改 M7。M9 不改 M8。每个里程碑通过三个集成点接入：`IndexManager.register()`、`EventBus.subscribe()`、`MetadataStore`。

**原则五：LLM 是建议者，不是权威**

M9 中，LLM 提取的记忆必须经过 Validator → Pipeline → ImportanceEngine 三道验证，才能成为真正的 MemoryEntry。LLM 可以提出建议，但不能直接写入。

---

## 2.4 一句话总结第二章

**Memory OS 像一个"终身学习的文件柜"：M6 造柜子，M7 帮你找文件，M8 给文件打分，M9 自动写新卡片，M10 定期清理旧文件。**

---

# 第三章：一次记忆的完整生命周期

## 3.1 从写入到检索的全流程

这是整个系统最重要的章节。我们跟踪一条记忆从"创建"到"被检索到"的每一步。

**场景**：Agent 发现一个重要信息，决定记住它：`"这个项目使用 pytest 做测试，测试文件放在 tests/ 目录"`

---

### 第一步：Agent 调用 memory_add

```
📁 src/memory/tools.py 第 37 行
```

Agent 调用 `memory_add` 工具，参数如下：

```python
{
    "type": "tool",
    "content": "这个项目使用 pytest 做测试，测试文件放在 tests/ 目录。运行测试的命令是 pytest tests/",
    "tags": ["testing", "pytest", "project-convention"],
    "importance": 0.7,
    "scope": "project"
}
```

---

### 第二步：创建 MemoryEntry

```
📁 src/memory/types.py 第 80 行
```

工具函数创建一个 `MemoryEntry` 对象。这个对象不是简单的字典，而是一个包含 6 个子结构的完整数据模型：

```python
MemoryEntry(
    identity=MemoryIdentity(    # 谁/什么/哪/什么时候
        id=MemoryID("abc123"),
        type=MemoryType.TOOL,
        scope=MemoryScope.PROJECT,
        state=MemoryState.ACTIVE,
    ),
    content=MemoryContent(      # 实际内容
        text="这个项目使用 pytest...",
        summary="使用 pytest 做测试",
        tags=["testing", "pytest", "project-convention"],
    ),
    ownership=MemoryOwnership(  # 权限信息
        creator=UserID("user1"),
        visibility=MemoryVisibility.PRIVATE,
    ),
    score=MemoryScore(          # 价值评分
        importance=0.7,
        confidence=0.5,
    ),
    relation=MemoryRelation(),  # 与其他记忆的关系
    version=MemoryVersion(),    # 版本追踪
)
```

---

### 术语解释：MemoryEntry 的 6 子结构

| 子结构 | 职责 | 生活比喻 |
|--------|------|----------|
| MemoryIdentity | 这条记忆的"身份证"——ID、类型、范围、状态 | 病历号 |
| MemoryContent | 实际内容——正文、摘要、标签 | 病历正文 |
| MemoryOwnership | 权限——谁创建的、谁能看到 | 只有主治医生能看 |
| MemoryScore | 动态评分——重要性、置信度、新鲜度 | 病历重要性评级 |
| MemoryRelation | 与其他记忆的关系——父记忆、子记忆 | "参见上次化验报告" |
| MemoryVersion | 版本信息——创建时间、修改次数 | 第几次复诊更新 |

---

### 第三步：进入 Pipeline（五道关卡）

```
📁 src/memory/pipeline.py 第 213 行
```

写入不是直接进 Store 的。每条记忆都要经过 Pipeline 的五道关卡：

```
memory_add 调用
      │
      ▼
┌──────────────┐
│ SchemaStage  │  第 1 关：Schema 校验
│ 优先级: 10   │  - 必填字段检查（type, content）
│              │  - 类型枚举检查（type 必须是 8 种之一）
│              │  - 内容长度检查
│              │  → 不通过：直接拒绝，返回错误原因
└──────┬───────┘
       │ 通过
       ▼
┌──────────────┐
│NormalizeStg  │  第 2 关：规范化
│ 优先级: 20   │  - 标签转小写、去前后空格
│              │  - 内容去首尾空白
│              │  - 摘要为空时自动从内容截取前 100 字
│              │  - 时间戳补全
└──────┬───────┘
       │ 通过
       ▼
┌──────────────┐
│DeduplicateStg│  第 3 关：去重
│ 优先级: 30   │  - 计算内容的 SHA256 哈希
│              │  - 与 Store 中已有条目比对
│              │  - 完全重复 → 拒绝，返回已有条目 ID
│              │  - 不重复 → 放行
└──────┬───────┘
       │ 通过
       ▼
┌──────────────┐
│PolicyCheckStg│  第 4 关：策略检查
│ 优先级: 40   │  - TypeAllowRule: 允许这种类型吗？
│              │  - ContentLengthRule: 内容长度在范围内吗？
│              │  - DuplicateRule: 允许重复吗？
│              │  - ScopeLimitRule: 超出范围限制了吗？
│              │  → 任一规则拒绝 → 返回拒绝原因
└──────┬───────┘
       │ 通过
       ▼
┌──────────────┐
│PersistStage  │  第 5 关：持久化
│ 优先级: 100  │  - 写入 Store 的 active 池
│              │  - 更新所有倒排索引
│              │  - 发射 CREATED 事件
│              │  → 磁盘 save()
└──────────────┘
```

---

### 术语解释：Pipeline（管道）

| 维度 | 说明 |
|------|------|
| 英文 | Pipeline |
| 中文 | 管道 / 处理流水线 |
| 一句话解释 | 数据在写入之前，经过一系列"关卡"，每道关卡做一件事 |
| 为什么出现 | 如果每个写入操作都要手动调用校验、去重、规则检查，代码会非常混乱。Pipeline 把这些步骤串起来，统一执行 |
| 本项目为什么需要 | 确保所有写入 Store 的记忆都是合法的、规范化的、不重复的、符合策略的 |
| 生活例子 | 机场安检：排队→检查登机牌→X光行李→金属探测门→放行。每一关做一件事，有问题的当场拒绝 |

---

### 第四步：M7 异步构建 Embedding

```
📁 src/memory/retrieval/embedding_worker.py
```

当 Store 发射 `CREATED` 事件后，M7 的 `EmbeddingWorker` 收到通知。

它会在**后台异步**做这件事：
1. 取出记忆的文本内容
2. 调用 Embedding 模型（如 text-embedding-3-small），把文本转成向量
3. 把向量存入 `VectorIndex`
4. 把向量存入 `MetadataStore`（方便恢复）

整个过程**不阻塞**主流程——Agent 可以继续跟用户对话。

---

### 术语解释：Embedding（嵌入 / 向量化）

| 维度 | 说明 |
|------|------|
| 英文 | Embedding |
| 中文 | 嵌入 / 向量化 |
| 一句话解释 | 把一段文字变成一个"数字数组"，让计算机能计算两段文字有多相似 |
| 为什么出现 | 计算机不会理解"pytest"和"单元测试"是相关的。但通过向量计算，它们的向量距离很近 |
| 本项目为什么需要 | 实现语义检索——用户搜"测试框架"，能找到标记为"pytest"的记忆 |
| 生活例子 | 图书馆给每本书打了一串"主题坐标"。你去找"编程"的书，图书管理员能顺便告诉你"软件工程"区的书也可能相关，因为它们的坐标很接近 |

---

### 第五步：M8 自动评分

```
📁 src/memory/importance/scoring.py
```

当 Store 发射 `CREATED` 事件，M8 的 `ImportanceScorer` 自动给新记忆打分：

```python
score = type_weight × source_weight + sigmoid_boost
```

- `type_weight`: 不同类型的基权。比如 `DECISION`（决策）天然比 `TOOL`（工具经验）重要
- `source_weight`: 来源权重。Agent 自动提取的 vs 用户手动创建的
- `sigmoid_boost`: S 形曲线加分。内容长度适中（500-2000 字）的加分

---

### 术语解释：Sigmoid Boost（S 形曲线加分）

| 维度 | 说明 |
|------|------|
| 英文 | Sigmoid Boost |
| 中文 | S 形曲线加分 |
| 一句话解释 | 用一条 S 形数学曲线给内容长度"恰好"的记忆加分，太短或太长的都不加分 |
| 为什么出现 | 太短的内容没信息量（"用 pytest"），太长的内容往往是垃圾（复制粘贴的日志），只有中等长度最有价值 |
| 生活例子 | 面试回答：只说"会"不行，说 30 分钟也不行。3-5 分钟的回答最受面试官欢迎 |

---

### 第六步：检索时被找到

```
📁 src/memory/retrieval/hybrid.py
```

后来，Agent 在处理一个测试相关的问题时，通过 `memory_search` 发起检索：

```python
RetrievalQuery(text="怎么写单元测试")
```

M7 的 `HybridRetriever` 从三个通道并行检索：

```
"怎么写单元测试"
      │
      ├─→ KeywordRetriever    (权重 0.3)
      │   搜索 "单元测试" → 命中 tags=["testing"], content 中有 "pytest"
      │   返回：[score=0.8] ← 这条记忆
      │
      ├─→ VectorRetriever     (权重 0.5)
      │   "怎么写单元测试" → Embedding → [0.02, 0.13, ...]
      │   vs 所有记忆的 Embedding → 余弦相似度
      │   返回：[score=0.92] ← 这条记忆（语义高度相似！）
      │
      └─→ RecentRetriever     (权重 0.2)
      │   最近 20 条记忆中，这条排第 3
      │   返回：[score=0.6]
      │
      ▼
   WeightedSumFusion
   0.3×0.8 + 0.5×0.92 + 0.2×0.6 = 0.82
      │
      ▼
   Reranker（二次排序）
   relevance × importance × freshness × frequency
   0.82 × 0.7 × 0.95 × 3 = 1.63
      │
      ▼
   最终排名：#1 → 返回给 Agent
```

---

### 术语解释：混合检索（Hybrid Retrieval）

| 维度 | 说明 |
|------|------|
| 英文 | Hybrid Retrieval |
| 中文 | 混合检索 |
| 一句话解释 | 同时用多种方式搜，把结果加权合并。单个检索方式有盲区，多种方式互补 |
| 为什么出现 | 关键词搜索能找到精确匹配（"pytest"），但找不到同义词（"测试框架"）。语义搜索能找到同义词，但可能漏掉精确匹配。两者互补 |
| 本项目为什么需要 | M7 的默认检索方式。确保 Agent 无论是搜精确工具名还是模糊概念，都能找到相关记忆 |
| 生活例子 | 你去图书馆找书：用"书名"搜是最准的（关键词），但如果你只知道大概主题，就需要图书管理员帮你推荐（语义）。两种方式结合起来效果最好 |

---

## 3.2 一句话总结第三章

**一条记忆从创建到被检索，经历了：创建 MemoryEntry → Pipeline 五道关卡 → 事件发射 → 异步 Embedding → 自动评分 → 最终在混合检索中被找到。**

---

# 第四章：M6 — Memory Core（10 子系统详解）

## 4.1 为什么需要 10 个子系统？

你可能会问：不就存个数据吗，需要 10 个系统？

我们来看一个简单的需求演变：

```
v0.1: "我就存点 key-value"
      → 一个 dict 就够了

v0.2: "我想按类型筛选记忆"
      → 需要类型索引 → IndexManager

v0.3: "写入之前得校验一下格式"
      → 需要 Schema → SchemaLayer

v0.4: "有人写了无效内容，得拒绝"
      → 需要规则检查 → PolicyEngine

v0.5: "我不小心创建了两条一模一样的记忆"
      → 需要去重 → DeduplicateStage

v0.6: "这个记忆的标签大小写不统一"
      → 需要规范化 → NormalizeStage

v0.7: "谁创建了这条记忆？什么时候？"
      → 需要身份追踪 → Identity 系统

v0.8: "我想知道谁改了哪条记忆"
      → 需要事件 → EventBus

v0.9: "这条记忆存了 3 个月了，要不要删？"
      → 需要生命周期管理 → LifecycleManager

v0.10: "我想让外部接入，但不能改我的 Store"
      → 需要类型注册 → Registry + Plugin
```

10 个子系统不是一次设计的，是一个一个长出来的。每个都解决一个真实问题。

---

## 4.2 10 个子系统一览

| # | 子系统 | 文件 | 一句话职责 |
|---|--------|------|-----------|
| 1 | Identity | `identity.py` | 6 种 ID 类型：MemoryID, UserID, ProjectID... |
| 2 | Types | `types.py` | MemoryEntry 的完整数据模型 |
| 3 | Events | `events.py` | 发布/订阅事件总线 |
| 4 | Schema | `schema.py` | 校验 → 序列化 → 反序列化 → 版本迁移 |
| 5 | Index | `index.py` | 5 种倒排索引 |
| 6 | Lifecycle | `lifecycle/manager.py` | 三池状态转移（Active/Archived/Deleted） |
| 7 | Policy | `policy.py` | 7 种规则插件 |
| 8 | Pipeline | `pipeline.py` | 5 阶段写入处理管线 |
| 9 | Registry | `registry.py` | 8 种内置记忆类型 + 插件接口 |
| 10 | Metadata | `metadata.py` | 解耦的键值扩展存储（存 embedding、OCR 等） |

---

## 4.3 Store：三池分离

```
📁 src/memory/store.py
```

`MemoryStore` 是纯存储层。它不搜索、不排名、不校验——只做 CRUD。

它最核心的设计是**三池分离**：

```
┌─────────────────────────────────────────────────────┐
│                    MemoryStore                       │
│                                                     │
│  ┌───────────────┐  ┌───────────────┐  ┌──────────┐│
│  │    Active     │  │   Archived    │  │  Deleted  ││
│  │   活跃池      │  │   归档池      │  │  删除池   ││
│  │               │  │               │  │           ││
│  │  正常参与     │  │  不参与检索   │  │  不参与   ││
│  │  检索和展示   │  │  但可恢复     │  │  检索     ││
│  │               │  │               │  │  可恢复   ││
│  └───────────────┘  └───────────────┘  └──────────┘│
│                                                     │
│  ┌─────────────────────────────────────────────────┐│
│  │              IndexManager（倒排索引）             ││
│  │  TypeIndex | TagIndex | ProjectIndex             ││
│  │  OwnerIndex | StateIndex                        ││
│  └─────────────────────────────────────────────────┘│
│                                                     │
│  ┌─────────────────────────────────────────────────┐│
│  │       LifecycleManager（状态转移管理）           ││
│  │  archive() | recover() | delete() | purge()     ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

**三个池的作用：**

- **Active（活跃池）**：正常状态。参与检索，参与上下文组装。
- **Archived（归档池）**：不参与检索，但数据还在。过时的、冷门的记忆放这里。可以随时恢复到 Active。
- **Deleted（删除池）**：软删除。不参与检索，但数据还在。可以恢复。只有 `purge()` 才真正删除。

为什么要三池？因为直接删除太危险。万一删错了呢？三池给了你一个"后悔药"。

---

### 术语解释：软删除（Soft Delete）

| 维度 | 说明 |
|------|------|
| 英文 | Soft Delete |
| 中文 | 软删除 |
| 一句话解释 | 标记为"已删除"，但数据还在。可以恢复。与之相对的是"硬删除"（数据彻底没了） |
| 为什么出现 | 防止误删。用户说"删了吧"可能不是真心的，3 秒后可能就后悔了 |
| 本项目为什么需要 | 记忆是长期积累的。误删一条重要记忆的代价很大。三池机制让你有 30 天的反悔期 |
| 生活例子 | 你电脑上的回收站/垃圾桶。删了文件，文件还在回收站里。只有"清空回收站"才是真的删了 |

---

## 4.4 Pipeline：五阶段处理管线

我们已经看过 Pipeline 的全流程（第三章第三步）。这里补充几个设计细节。

### 可插拔阶段

```
📁 src/memory/pipeline.py 第 28 行
```

每个阶段都实现 `PipelineStage` 抽象基类：

```python
class PipelineStage(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """阶段名称"""
        ...

    @abstractmethod
    def process(self, entry, store) -> (bool, str, MemoryEntry):
        """返回 (是否接受, 原因, 处理后条目)"""
        ...

    def priority(self) -> int:
        """优先级，越小越先执行。默认 50"""
        return 50
```

你可以写自己的阶段，比如一个"敏感词过滤"阶段：

```python
class SensitiveWordStage(PipelineStage):
    name = "sensitive_word"

    def process(self, entry, store):
        if "password" in entry.content.text.lower():
            return False, "检测到敏感词", entry
        return True, "ok", entry

    def priority(self):
        return 25  # 在 normalize 之后，deduplicate 之前
```

然后注册：

```python
core.pipeline.register_stage(SensitiveWordStage(), after="normalize")
```

`after=` 参数可以精确控制插入位置。新阶段不需要改任何旧代码。

---

## 4.5 Events：事件总线

```
📁 src/memory/events.py
```

`MemoryEventBus` 是 Memory OS 的"神经系统"。所有变更都发射事件，所有关心变更的组件都订阅事件。

**9 种事件类型：**

| 事件 | 触发时机 | 谁订阅了 |
|------|---------|---------|
| `CREATED` | 新记忆创建 | M7 EmbeddingWorker（异步 embed）、M8 Scorer（自动评分） |
| `UPDATED` | 记忆被更新 | M7 EmbeddingWorker（重新 embed） |
| `DELETED` | 记忆被软删除 | M7 VectorIndex（移除向量） |
| `ARCHIVED` | 记忆被归档 | M7 VectorIndex（移除向量） |
| `RECOVERED` | 记忆被恢复 | M7 EmbeddingWorker（重新 embed） |
| `PURGED` | 记忆被硬删除 | M7 VectorIndex（移除向量）、GC |
| `ACCESSED` | 记忆被检索到 | M8 AccessTracker（更新访问频率） |
| `MERGED` | 两条记忆合并 | M7 VectorIndex（更新向量） |
| `VACUUMED` | 低价值记忆被清理 | Lifecycle Metrics |

**关键设计：**
- 发射事件的代码不关心谁在听
- 订阅事件的代码不关心谁在发射
- 双方只通过 `MemoryEventBus` 交互

这意味着你可以在任何时候添加新的订阅者，不影响已有功能。

---

### 术语解释：事件总线（Event Bus）

| 维度 | 说明 |
|------|------|
| 英文 | Event Bus |
| 中文 | 事件总线 |
| 一句话解释 | 一个"广播系统"。有人发消息，所有订阅了这个消息类型的人都能收到 |
| 为什么出现 | 让系统中不同的模块在不直接依赖彼此的情况下通信 |
| 本项目为什么需要 | M7、M8、M9 都需要知道"什么时候创建了新记忆"，但不能直接 import 对方的代码 |
| 生活例子 | 小区广播。有人广播"失物招领"，整个小区都能听到。关心的人会去认领，不关心的人忽略。广播的人不需要知道谁会来认领 |

---

## 4.6 Policy：7 种规则插件

```
📁 src/memory/policy.py
```

`PolicyEngine` 是一个规则引擎。它有 7 种内置规则：

| 规则 | 职责 | 默认行为 |
|------|------|---------|
| `TypeAllowRule` | 允许/拒绝某些类型 | 允许所有类型 |
| `ContentLengthRule` | 内容长度限制 | 1-50000 字符 |
| `ContentPatternRule` | 正则匹配（禁词、敏感词） | 无禁词 |
| `DuplicateRule` | 是否允许重复内容 | 不允许重复 |
| `ScopeLimitRule` | 每个 Scope 最多多少条 | 无限制 |
| `TypeLimitRule` | 每种 Type 最多多少条 | 无限制 |
| `SourceRule` | 允许/拒绝某些来源 | 允许所有来源 |

每条规则都实现 `PolicyRule` ABC：

```python
class PolicyRule(ABC):
    @abstractmethod
    def check(self, entry, store, config) -> (bool, str):
        """返回 (是否通过, 不通过时的原因)"""
        ...
```

你可以随时添加自定义规则：

```python
core.policy.register_rule(MyCustomRule())
```

---

## 4.7 Registry：类型与插件

```
📁 src/memory/registry.py
```

`MemoryRegistry` 管理记忆的"类型系统"。它内置了 8 种类型：

| 类型 | 含义 | 默认 Scope | 举例 |
|------|------|-----------|------|
| `USER` | 用户偏好、习惯、背景 | PROJECT | "用户喜欢用 tab 缩进" |
| `PROJECT` | 项目约定、结构 | PROJECT | "所有 API 路由放在 routes/ 下" |
| `CONVERSATION` | 对话中的关键结论 | SESSION | "用户说要在周五前完成" |
| `DECISION` | 架构/技术决策 | PROJECT | "选择 SQLAlchemy 而不是原始 SQL" |
| `EXPERIENCE` | 踩过的坑、教训 | PROJECT | "上次升级 Python 3.12 后 asyncio 崩了" |
| `TOOL` | 工具使用经验 | PROJECT | "pytest --lf 可以只跑上次失败的测试" |
| `KNOWLEDGE` | 通用领域知识 | GLOBAL | "JWT 的刷新机制是..." |
| `CODE` | 代码模式、最佳实践 | PROJECT | "用 dataclass 而不是 dict" |

每种类型都有默认的 scope 和 visibility，在 Registry 中注册：

```python
MemoryTypeDefinition(
    type=MemoryType.DECISION,
    description="技术/架构决策",
    default_scope=MemoryScope.PROJECT,
    default_visibility=MemoryVisibility.TEAM,
    icon="🔧",
)
```

外部也可以通过 `MemoryPlugin` 接口扩展自定义类型。

---

## 4.8 其余子系统速览

### IndexManager（`src/memory/index.py`）

5 种倒排索引，加速查找：

```python
# 找所有 tool 类型的记忆
TypeIndex:    "tool" → [MemoryID1, MemoryID2, ...]

# 找所有带 testing 标签的记忆
TagIndex:     "testing" → [MemoryID1, MemoryID3, ...]

# 找某个项目下的所有记忆
ProjectIndex: "my-project" → [MemoryID1, ...]

# 找某个人创建的所有记忆
OwnerIndex:   "user1" → [MemoryID1, ...]

# 找所有 active 状态的记忆
StateIndex:   "active" → [MemoryID1, MemoryID2, ...]
```

每个索引都是 `Index` ABC 的实现，可以动态注册新的索引类型。

---

### SchemaLayer（`src/memory/schema.py`）

负责：
- **校验**：`validate(entry) → SchemaResult`，检查必填字段、类型枚举、内容长度
- **序列化**：`serialize(entry) → dict`
- **反序列化**：`deserialize(data) → MemoryEntry`
- **迁移**：`migrate(data) → dict`，通过 BFS 找最短迁移路径

Schema 版本当前是 "1.0"。以后如果 MemoryEntry 加字段，通过 `MigrationRegistry` 注册迁移步骤：

```python
migration_registry.register("1.0", "2.0", migrate_v1_to_v2)
migration_registry.register("2.0", "2.1", migrate_v2_to_v2_1)
```

系统自动找到最短路径：如果数据是 1.0，目标是 2.1，它会找 `1.0 → 2.0 → 2.1`。

---

### Identity（`src/memory/identity.py`）

6 种 ID 类型，都是不可变的 frozen dataclass：

- `MemoryID` — 记忆的唯一标识
- `UserID` — 用户标识
- `ProjectID` — 项目标识
- `WorkspaceID` — 工作区标识
- `SessionID` — 会话标识
- `AgentID` — Agent 实例标识

所有 ID 都是 hashable 的，可以作为 dict 的 key。

---

### Metadata（`src/memory/metadata.py`）

`MetadataStore` 是一个"记忆的扩展存储"。它存的东西不是 MemoryEntry 的字段，而是和记忆相关的附加数据：

- Embedding 向量（M7）
- OCR 结果
- 插件自定义数据
- 附件/图片的二进制数据

它和 Store 完全解耦——删除 Metadata 不影响 Store，反之亦然。

---

## 4.9 一句话总结第四章

**M6 的 10 个子系统像一个"精密文件柜"：Store 是抽屉，Pipeline 是门禁，Policy 是管理员，Events 是广播系统，Index 是目录卡，Registry 是分类标准。**

---

# 第五章：M7 — Retrieval Engine（检索引擎）

## 5.1 核心问题：怎么找到最相关的记忆？

当 Agent 说"帮我找关于测试的记忆"，Memory OS 里有 500 条记忆。怎么找到最相关的 5 条？

M7 的答案是：**三种方式同时搜，加权合并，二次排序。**

---

## 5.2 三通道检索

```
📁 src/memory/retrieval/retriever.py
```

| 通道 | 检索器 | 原理 | 适用场景 |
|------|--------|------|---------|
| Keyword | `KeywordRetriever` | TF-IDF 加权匹配（内容 1x / 摘要 3x / 标签 5x） | 精确匹配：API 名、文件名、专有名词 |
| Vector | `VectorRetriever` | Embedding → 余弦相似度 | 语义匹配："测试框架" ↔ "pytest" |
| Recent | `RecentRetriever` | 时间降序，最近 20 条 | 近期上下文不丢 |

---

### KeywordRetriever 的 TF-IDF 加权

```
📁 src/memory/retrieval/retriever.py (KeywordRetriever)
```

TF-IDF（Term Frequency - Inverse Document Frequency，词频-逆文档频率）是一种经典的文本匹配算法。

- TF（词频）：这个词在这篇文档中出现了多少次
- IDF（逆文档频率）：这个词在其他文档中有多罕见

在 M7 中，KeywordRetriever 给不同字段不同的权重：
- 标签匹配：5x（标签是最精确的信号）
- 摘要匹配：3x（摘要是内容的浓缩）
- 正文匹配：1x（基础权重）

---

### VectorRetriever 与余弦相似度

```
📁 src/memory/retrieval/vector_index.py
```

默认使用 `NumPyVectorIndex`——暴力计算查询向量与所有记忆向量的余弦相似度。

```
余弦相似度 = (A · B) / (|A| × |B|)

结果范围：[-1, 1]。1 表示完全相同，0 表示不相关，-1 表示完全相反。
```

`BaseVectorIndex` 是抽象基类。未来可以替换为 FAISS（Facebook 的向量检索引擎）或 Milvus（分布式向量数据库），只需实现同一个接口。Retriever 的代码不用改。

---

### 术语解释：向量索引（Vector Index）

| 维度 | 说明 |
|------|------|
| 英文 | Vector Index |
| 中文 | 向量索引 |
| 一句话解释 | 一个专门为"找最相似的向量"而优化的数据结构 |
| 为什么出现 | 当你有 100 万条记忆时，每条都和查询算一遍相似度太慢了。向量索引用近似算法大幅加速 |
| 本项目为什么需要 | Phase 1 用 NumPy 暴力计算（适合 < 10000 条），Phase 2 可换 FAISS/Milvus |
| 生活例子 | 图书馆的书架编排。如果所有书随机摆放，你每次要找一本就翻遍整个图书馆。但按"主题-作者-年份"排列后，你能快速定位 |

---

## 5.3 融合策略：WeightedSumFusion

```
📁 src/memory/retrieval/hybrid.py 第 31 行
```

三个通道的结果怎么合在一起？默认使用加权和融合：

```python
Weights: {
    "keyword": 0.3,   # 关键词权重
    "vector":  0.5,   # 语义权重（最高——语义通常最有用）
    "recent":  0.2,   # 最近权重
}
```

融合步骤：
1. 每个通道的结果分数归一化到 [0, 1]
2. 按权重乘各自的分数
3. 同一记忆从多个通道被召回时，分数累加
4. 按总分降序排列

备选方案：`ReciprocalRankFusion`（RRF，倒数排名融合）——不关心绝对分数，只关心排名：

```
RRF_score = Σ 1/(k + rank_in_channel)

k 是常数（默认 60），用来防止单通道排名过高的条目主导结果。
```

RRF 的优势：不关心不同通道的分数尺度差异（有的通道给 0.9 已经很高，有的通道给 0.5 就很高）。更鲁棒。

---

### 术语解释：融合策略（Fusion Strategy）

| 维度 | 说明 |
|------|------|
| 英文 | Fusion Strategy |
| 中文 | 融合策略 |
| 一句话解释 | 多个检索通道的结果怎么合并成一个排名列表的算法 |
| 为什么出现 | 不同通道的"分数"含义不同。关键词的 0.9 和语义的 0.9 不是一回事。不能直接加 |
| 本项目为什么需要 | M7 用三个通道搜，必须有一个公平的方式合并结果 |
| 生活例子 | 选秀节目：评委 A 打分激进（经常给 90+），评委 B 保守（很少给 80+）。直接加分会偏向评委 A。需要"归一化"后再合并 |

---

## 5.4 Reranker：二次排序

```
📁 src/memory/retrieval/ranker.py
```

混合检索返回了 50 条候选记忆。Reranker 做第二遍精排：

```
final_score = relevance × importance × freshness × frequency
```

- **relevance**：检索相关性分数（来自 Hybrid 融合）
- **importance**：M8 的重要性分数（越重要越高）
- **freshness**：新鲜度（越新越高，指数衰减）
- **frequency**：访问频率（被检索到的次数越多越高）

这确保了检索结果不只是"语义上相关"，而且是"重要的、新鲜的、经常被用到的"。

---

## 5.5 MemoryPlanner：任务感知检索

```
📁 src/memory/retrieval/planner.py
```

`MemoryPlanner` 是 M7 的"大脑"。它不是盲目检索，而是先分析用户在做什么，再决定搜什么。

```python
TaskContext(current_query="给 auth.py 加刷新 token 功能")
      │
      ▼
MemoryPlanner.plan(task) → RetrievalIntent
      │
      ├─ targets: ["auth", "token", "JWT", "refresh"]
      ├─ types: [DECISION, TOOL, EXPERIENCE]  # 优先找决策和工具经验
      ├─ recency_bias: True                    # 偏向近期记忆
      └─ max_results: 10
      │
      ▼
RetrievalEngine.retrieve(intent) → 精准检索
```

Planner 在 Phase 1 用规则（关键词提取 + 类型映射），Phase 2 可升级为 LLM 规划。

---

## 5.6 异步 Embedding Worker

```
📁 src/memory/retrieval/embedding_worker.py
```

写入记忆时不阻塞。Embedding 是后台做的：

```
Store 发射 CREATED 事件
      │
      ▼
EmbeddingWorker 收到（后台线程）
      │
      ├─ 1. 取文本：content.summary + content.text 的前 500 字符
      ├─ 2. 调 Embedding 模型：text → [0.02, 0.13, ...]
      ├─ 3. 存 VectorIndex
      └─ 4. 存 MetadataStore（以 "embedding" 为 key）
```

如果 Embedding 模型调用失败，Worker 会静默跳过（不会影响主流程），MemoryEntry 已经安全地存入了 Store。

---

## 5.7 一句话总结第五章

**M7 像一个"三人搜查小组"：一个人查标签，一个人搜同义词，一个人翻最新的。三人的线索合在一起，再加上"这条记忆重要吗？新鲜吗？经常用吗？"的二次判断，最后给出最相关的结果。**

---

# 第六章：M8 — Importance Engine（重要性引擎）

## 6.1 核心问题：500 条记忆，哪些重要？

不是所有记忆都一样重要。

- "用户叫张顺杰"——重要，每次都要知道
- "上次用 pandas 读了一个 CSV"——不太重要，忘了也无所谓

M8 的目标：给每条记忆一个**动态分数**。重要的浮上来，过时的沉下去。

---

## 6.2 五个组件

```
📁 src/memory/importance/engine.py
```

| 组件 | 职责 | 触发方式 |
|------|------|---------|
| `ImportanceScorer` | 初始评分：type_weight × source_weight + sigmoid_boost | CREATED 事件 |
| `FreshnessDecay` | 指数衰减：分数随时间下降 | 懒加载 + ACCESSED 事件 |
| `AccessTracker` | 跟踪访问频率、最后访问时间 | ACCESSED 事件 |
| `FeedbackHandler` | 处理用户显式反馈（有用/没用） | Agent 调用 memory_feedback |
| `VacuumPolicy` | 检测低价值记忆，发射 VACUUMED 事件 | 定期检查 |

---

## 6.3 初始评分：ImportanceScorer

```
📁 src/memory/importance/scoring.py
```

新记忆创建时，Scorer 自动打分：

```python
base_score = type_weight × source_weight

# type_weight 示例：
# DECISION: 0.9  → 决策很重要
# EXPERIENCE: 0.8 → 踩坑经验也很重要
# USER: 0.85     → 用户偏好重要
# CODE: 0.6      → 代码模式中等
# TOOL: 0.5      → 工具经验一般

# source_weight 示例：
# user_explicit: 1.0    → 用户手动创建的最可信
# agent_extracted: 0.7  → Agent 自动提取的次之
# system_generated: 0.5 → 系统自动生成的再次

# sigmoid_boost：
# 内容长度在 500-2000 字符之间 → +0.1 ~ +0.2
# 太短或太长 → 不加分
```

---

## 6.4 指数衰减：FreshnessDecay

```
📁 src/memory/importance/decay.py
```

记忆不是越老越好。一条"用 Python 2.7 的方法"可能曾经很重要，但现在过时了。

```python
freshness = e^(-λ × days_since_last_access)

# λ（衰减率）可配置，默认下：
# 7 天不访问：freshness ≈ 0.5
# 30 天不访问：freshness ≈ 0.05
# 90 天不访问：freshness ≈ 0.0001
```

当记忆被检索到时（ACCESSED 事件），freshness 重置为 1.0，重新计时。

**关键设计**：衰减不是定时器驱动的（不用每秒钟检查所有记忆），而是**懒加载**——只有当记忆被检索/访问时，才计算当前的新鲜度。节省计算资源。

---

### 术语解释：指数衰减（Exponential Decay）

| 维度 | 说明 |
|------|------|
| 英文 | Exponential Decay |
| 中文 | 指数衰减 |
| 一句话解释 | 一个值以固定比例下降。开始降得快，后面降得慢。数学公式是 e^(-λ × t) |
| 为什么出现 | 自然界的遗忘规律：昨天的事记得很清楚，上周的事有点模糊，去年的事基本忘了 |
| 本项目为什么需要 | 让旧记忆自动贬值，不被频繁访问的记忆自然沉到底部 |
| 生活例子 | 一杯热水放在桌上。第一分钟降温很快（70°C→50°C），第 10 分钟降温变慢（35°C→33°C），最后接近室温。这就是指数衰减 |

---

## 6.5 访问追踪：AccessTracker

```
📁 src/memory/importance/tracking.py
```

`AccessTracker` 订阅 `ACCESSED` 事件，记录：

```python
{
    memory_id: "abc123",
    access_count: 15,            # 总共被访问的次数
    last_accessed: 1719600000,   # 最后访问时间
    access_streak: 3,            # 连续被访问的会话数
    first_accessed: 1719000000,  # 首次访问时间
}
```

这些数据被 M7 的 Reranker 使用（`frequency` 因子）和 M8 的 FreshnessDecay 使用。

---

## 6.6 显式反馈：FeedbackHandler

```
📁 src/memory/importance/feedback.py
```

Agent 可以通过 `memory_feedback` 工具给记忆打分：

```python
# Agent 调用
memory_feedback(memory_id="abc123", rating="useful")
```

三种反馈等级：

| 反馈 | 效果 |
|------|------|
| `"useful"` | confidence +0.1, importance 微调 +0.05 |
| `"not_useful"` | confidence -0.1, importance 微调 -0.05 |
| `"critical"` | importance 直接设为 0.95, confidence = 1.0 |

用户/Agent 的显式反馈是最强烈的信号——它能覆盖自动评分的结果。

---

## 6.7 清理：VacuumPolicy

```
📁 src/memory/importance/vacuum.py
```

`VacuumPolicy` 定期检查，找到应该被清理的记忆：

```python
should_vacuum = (
    importance < 0.1                    # 重要性极低
    and freshness < 0.05                # 很久没被访问
    and access_count < 3                # 几乎没被用过
    and days_since_creation > 30        # 至少存在了 30 天
)
```

被标记为 VACUUMED 的记忆不会自动删除——只是发射事件通知。M10 的 GC 会决定是否真正清理。

---

## 6.8 一句话总结第六章

**M8 像一个"记忆管家"：新记忆自动打分，旧记忆自然贬值，经常被用的保持新鲜，用户点赞的加分，没用的标记清理。**

---

# 第七章：M9 — Intelligence Engine（智能引擎）

## 7.1 核心问题：记忆不能只靠人手写

你不能指望用户（或 Agent）每次学到新东西都手动调用 `memory_add`。那太累了，而且不可靠。

M9 的目标：**让 Memory OS 自动从对话中学习。**

---

## 7.2 设计哲学：LLM 是建议者，不是权威

```
LLM 提出建议 → Validator 校验 → Pipeline 写入 → Importance Engine 评分
     ↑                                                      │
     └───────── 反馈循环（记忆质量影响未来提取质量）─────────┘
```

LLM 可以：
- 从对话中提取可能重要的信息
- 检测两条记忆是否矛盾
- 建议合并相似记忆

LLM **不能**：
- 直接写入 Store
- 直接修改已有记忆
- 绕过 Pipeline

每一段 LLM 提出的记忆，都要经过和 `memory_add` 完全相同的五道关卡。

---

### 术语解释：建议者模式（Proposer-Authority Pattern）

| 维度 | 说明 |
|------|------|
| 英文 | Proposer-Authority Pattern |
| 中文 | 建议者-权威模式 |
| 一句话解释 | 一个组件可以提建议，但另一个组件有权拒绝。像"你可以提立法建议，但议会才有权通过法律" |
| 为什么出现 | LLM 会"幻觉"——它可能提取出不存在的事实或错误的知识。必须有把关机制 |
| 本项目为什么需要 | M9 用 LLM 自动学习，但必须保证记忆库的质量。Validator + Pipeline 就是把关人 |
| 生活例子 | 实习生可以提议"我们应该把这个客户升级为 VIP"，但经理才有权批准。实习生是 Proposer，经理是 Authority |

---

## 7.3 八个组件

```
📁 src/memory/intelligence/engine.py
```

| 组件 | 职责 |
|------|------|
| `TriggerPolicy` | 决定"什么时候该学习了" |
| `KnowledgeExtractor` | 从对话中提取知识 |
| `ReflectionEngine` | 定期反思：合并、冲突检测、细化、拆分 |
| `AsyncWorker` | 后台线程跑 LLM 调用，不阻塞主流程 |
| `CandidateValidator` | 校验 LLM 提出的候选记忆 |
| `ResponseParser` | 把 LLM 返回的 JSON 转成 MemoryCandidate |
| `PromptLoader` | 加载 Prompt 模板（支持变量替换） |
| `Strategies (Merge/Conflict/Refine/Split)` | 四种反思策略 |

---

## 7.4 知识提取：KnowledgeExtractor

```
📁 src/memory/intelligence/extractor.py
```

提取流程：

```
对话历史（最近 10 轮）
      │
      ▼
PromptLoader 加载模板
  → extract_system.md (系统指令)
  → extract_user.md (用户指令，填充对话内容)
      │
      ▼
LLM 分析 → 结构化输出
  {
    "candidates": [
      {
        "type": "decision",
        "content": "选择 FastAPI 而不是 Flask，因为需要异步支持",
        "summary": "Web 框架选型：FastAPI",
        "tags": ["fastapi", "decision", "web-framework"],
        "importance": 0.8,
        "confidence": 0.9
      },
      {
        "type": "tool",
        "content": "使用 alembic 做数据库迁移，命令是 alembic upgrade head",
        "summary": "数据库迁移工具：alembic",
        "tags": ["alembic", "database", "migration"],
        "importance": 0.6,
        "confidence": 0.85
      }
    ]
  }
      │
      ▼
ResponseParser 解析 → MemoryCandidate 列表
      │
      ▼
CandidateValidator 校验
  → content 不能为空
  → type 必须在 8 种之内
  → 和已有记忆的语义相似度 > 0.95 → 拒绝（重复）
      │
      ▼
通过校验的 → 进入 Pipeline（五道关卡）
不通过的 → 丢弃，记录日志
```

---

## 7.5 触发策略：TriggerPolicy

```
📁 src/memory/intelligence/trigger.py
```

不是每轮对话都提取。触发条件：

| 事件 | 说明 |
|------|------|
| `TASK_END` | 一个任务完成时（最常用） |
| `IDLE` | Agent 空闲超过 N 秒 |
| `MESSAGE_THRESHOLD` | 累积了 N 轮新对话（默认 10 轮） |
| `USER_COMMAND` | 用户显式调用 `memory_extract` 工具 |
| `DECISION_DETECTED` | 检测到"我们决定…"、"选择…"等关键词 |

最常用的是 `TASK_END`——Agent 完成一个任务后，自动反思"我学到了什么"。

---

## 7.6 反思引擎：ReflectionEngine

```
📁 src/memory/intelligence/reflector.py
```

`ReflectionEngine` 是一个定期运行的"复习"过程。它不提取新知识，而是审视已有记忆：

**四种策略：**

```
Merge（合并）
  发现两条记忆非常相似（语义相似度 > 0.85）
  → LLM 判断：该不该合并？
  → 合并成一条，保留最重要的信息
  → 旧的两条标记为 ARCHIVED

Conflict（冲突）
  发现两条记忆可能矛盾
  记忆 A："用户用 tab 缩进"
  记忆 B："用户用 4 空格缩进"
  → LLM 判断：真矛盾还是不同语境？
  → 真矛盾 → 保留更新的，归档旧的
  → 不同语境 → 两条都保留，加备注

Refine（细化）
  一条记忆太笼统
  "用户喜欢简洁的代码风格"
  → LLM 补充具体信息
  → "用户喜欢：单行不超过 80 字符、函数不超过 20 行、用 dataclass 而不是 dict"

Split（拆分）
  一条记忆包含太多信息
  "后端用 FastAPI+SQLAlchemy+Alembic+Redis+Celery，前端用 React+TypeScript"
  → LLM 拆分成 5 条独立记忆
  → 每条都是独立的知识点，检索更精准
```

---

### 术语解释：反思（Reflection）

| 维度 | 说明 |
|------|------|
| 英文 | Reflection |
| 中文 | 反思 |
| 一句话解释 | AI 不是一直往前冲，而是定期停下来"想一想"。看看已有的记忆有没有矛盾、有没有可以合并的 |
| 为什么出现 | 自动提取的记忆可能出错、可能重复、可能矛盾。需要定期"打扫" |
| 本项目为什么需要 | M9 的自动学习会产生"脏数据"。Reflection 是质量保证的最后一道防线 |
| 生活例子 | 你每周末整理手机相册：发现拍了两张一模一样的 → 删掉一张（Merge），发现截图里有个有用的信息 → 单独保存（Split），模糊的照片 → 删掉 |

---

## 7.7 Prompt 模板系统

```
📁 src/memory/intelligence/prompts/
```

M9 的 LLM 调用使用结构化的 Prompt 模板（Markdown 文件）：

```
prompts/
├── extract_system.md    ← 提取时的系统指令
├── extract_user.md      ← 提取时的用户指令（含对话内容变量）
├── merge_system.md      ← 合并时的系统指令
├── merge_user.md        ← 合并时的用户指令
├── conflict_system.md   ← 冲突检测的系统指令
├── conflict_user.md     ← 冲突检测的用户指令
├── refine_system.md     ← 细化时的系统指令
├── refine_user.md       ← 细化时的用户指令
├── split_system.md      ← 拆分时的系统指令
└── split_user.md        ← 拆分时的用户指令
```

每个模板支持变量替换：`{{conversation}}`、`{{existing_memories}}`、`{{task_context}}`。

模板的存在使得你可以在不修改代码的情况下调整 LLM 的行为。

---

## 7.8 一句话总结第七章

**M9 像一个"自动笔记员"：Agent 工作完，它自动在后台总结学到了什么（提取），定期翻翻笔记看看有没有矛盾（反思），提出修改建议让 Pipeline 和 Validator 把关。**

---

# 第八章：M10 — Lifecycle Engine（生命周期引擎）

## 8.1 核心问题：记忆库的健康管理

用了三个月后，Memory OS 里有 3000 条记忆。其中：

- 800 条已经过时了（Python 3.6 的语法）
- 300 条是重复的（同一个决策记录了 3 次）
- 200 条太久没访问了（可能是没用的）
- 50 条的内容已经失效（引用的代码被删了）

M10 的目标：**自动保持记忆库的健康。**

---

## 8.2 六个组件

```
📁 src/memory/lifecycle/engine.py
```

| 组件 | 职责 |
|------|------|
| `LifecyclePolicyEngine` | 统一策略管理 |
| `LifecycleStateMachine` | 加权状态转移 |
| `ArchiveEngine` | 策略驱动的自动归档 |
| `MemoryCompressor` | 对一组记忆做压缩（RuleBased/LLM/Hybrid） |
| `GarbageCollector` | 清理/验证/修复（不硬删除） |
| `LifecycleWorker` | 后台定期调度 |
| `LifecycleMetricsCollector` | 健康仪表盘 |

---

## 8.3 状态转移：从 ACTIVE 到 DELETED

```
📁 src/memory/lifecycle/state.py
```

每条记忆有 5 种状态，8 种转移路径：

```
                    ┌─────────┐
         ┌─────────→│  ACTIVE │←─────────┐
         │ recover  │  (活跃)  │ create    │
         │          └────┬─────┘           │
         │               │                 │
         │          archive                │ warm_up
         │               │                 │
         │               ▼                 │
    ┌────┴─────┐   ┌─────────┐   ┌────────┴─────┐
    │ DELETED  │←──│ARCHIVED │←──│    WARM      │
    │ (已删除) │   │ (已归档) │   │   (温热)     │
    └──────────┘   └─────────┘   └──────┬───────┘
         │                              │
         │ purge      ┌─────────┐      │ cool_down
         └───────────→│  COLD   │←─────┘
        (硬删除，     │ (冷却)  │
         不可恢复)    └─────────┘
```

**状态解释：**

| 状态 | 含义 | 参与检索？ |
|------|------|-----------|
| `ACTIVE` | 正常状态 | ✅ 完全参与 |
| `WARM` | 被访问中，但新鲜度开始衰减 | ✅ 参与 |
| `COLD` | 长期未访问，重要性低 | ⚠️ 仅在显式搜索时 |
| `ARCHIVED` | 已归档，可恢复 | ❌ 不参与 |
| `DELETED` | 软删除，可恢复 | ❌ 不参与 |

**转移条件示例：**
- `ACTIVE → WARM`：7 天未被访问
- `WARM → COLD`：30 天未被访问
- `COLD → ARCHIVED`：60 天未被访问
- `ARCHIVED → DELETED`：ArchiveEngine 触发（默认归档后 90 天）
- `DELETED → (真正删除)`：只有 `purge()` 硬删除

---

### 术语解释：状态机（State Machine）

| 维度 | 说明 |
|------|------|
| 英文 | State Machine |
| 中文 | 状态机 |
| 一句话解释 | 一个东西只能处于一种"状态"，在满足条件时跳到另一个状态。所有状态和跳转规则加在一起就是状态机 |
| 为什么出现 | 让状态的变化有规矩可循——不是谁都能随便改 |
| 本项目为什么需要 | 记忆有很多状态（活跃、温热、冷却、归档、删除），转移的逻辑很复杂。状态机让这些逻辑清晰可控 |
| 生活例子 | 快递的状态：已下单→已揽件→运输中→派送中→已签收。每个状态只能跳到特定的下一个状态。你不能从"已下单"直接跳到"已签收" |

---

## 8.4 ArchiveEngine：自动归档

```
📁 src/memory/lifecycle/archiver.py
```

`ArchiveEngine` 按策略自动归档：

```python
# 归档条件（可配置）
archive_if:
  - state == COLD
  - days_since_last_access > 60
  - importance < 0.2
  - NOT type == DECISION  # 决策不归档（永远保留）
  - NOT tags contains "critical"  # 标记为关键的永远保留
```

归档前发射 `ARCHIVED` 事件 → VectorIndex 移除对应向量 → Metadata 保留。

---

## 8.5 MemoryCompressor：记忆压缩

```
📁 src/memory/lifecycle/compressor.py
```

当一组同类记忆太多时，不删除，而是**压缩**。

三种策略：

| 策略 | 做法 | 场景 |
|------|------|------|
| `RuleBasedCompression` | 规则合并：同名工具的经验取最新 3 条 | 快速、免费 |
| `LLMCompression` | LLM 总结 5 条 TOOL 记忆为 1 条 | 质量最高，但花钱 |
| `HybridCompression` | 先用规则筛选，再用 LLM 总结 | 性价比最高 |

示例：

```
压缩前（5 条记忆）：
  "用 pytest --lf 可以只跑失败的测试"
  "pytest -x 遇到失败就停"
  "pytest --ff 先跑上次失败的"
  "pytest -k 'pattern' 按模式筛选"
  "pytest --maxfail=3 最多失败3次就停"

压缩后（1 条记忆）：
  "pytest 常用选项：--lf（只跑失败）、-x（遇错即停）、--ff（优先失败）、
   -k pattern（模式筛选）、--maxfail=N（限制失败数）"
```

---

## 8.6 GarbageCollector：垃圾回收

```
📁 src/memory/lifecycle/gc.py
```

`GarbageCollector`（GC）做三件事，但**不硬删除**：

**Clean（清理）**：
- 发现 COLD 超过 N 天的记忆 → 标记为 ARCHIVED
- 发现 DELETED 超过 N 天的记忆 → 发射清理建议

**Validate（验证）**：
- 检查 MemoryEntry 的引用是否有效（比如引用的父记忆是否还存在）
- 检查 Metadata 是否完整（有 Embedding 吗？）
- 检查 Index 是否一致（Store 里有但 Index 里没有？）

**Repair（修复）**：
- 修复断裂的引用 → 改为指向最近的有效条目
- 补全缺失的 Embedding → 重新调用 embed
- 修复 Index 不一致 → 重建受影响索引

---

## 8.7 LifecycleWorker：后台调度

```
📁 src/memory/lifecycle/worker.py
```

所有 M10 操作在后台定期运行：

```python
schedule:
  every 1 hour:    ArchiveEngine.run()       # 归档检查
  every 6 hours:   GarbageCollector.clean()   # 垃圾清理
  every 24 hours:  GarbageCollector.validate() # 完整性检查
  every 7 days:    MemoryCompressor.run()      # 记忆压缩
  every 30 days:   GarbageCollector.repair()   # 引用修复
```

---

## 8.8 一句话总结第八章

**M10 像一个"记忆库管理员"：定期归档旧记忆、压缩重复内容、清理垃圾、修复断裂引用，让记忆库始终保持健康。**

---

# 第九章：Context OS 桥接

## 9.1 记忆如何出现在上下文中？

Memory OS 存了 500 条记忆。但发给大模型的 Prompt 空间有限——可能只有 2000 token 留给记忆。

怎么决定"哪些记忆应该出现在这轮对话的上下文中"？

答案：MemoryLayer + MemoryCollector。

---

## 9.2 MemoryLayer：桥接层

```
📁 src/memory/layer.py
```

`MemoryLayer` 继承 `BaseLayer`（Context OS 的抽象基类），让 Memory OS 可以像其他 Context Layer 一样被注册和使用。

```python
# main.py 组装
memory_layer = MemoryLayer(memory_core)
orchestrator.register_layer(memory_layer, position=2)
```

`MemoryLayer.render()` 有两个阶段：

**Phase 1（M6，无检索）**：
```python
def _render_phase1(self):
    all_active = store.get_active()
    sorted_memories = sorted(
        all_active,
        key=lambda m: m.score.importance * m.freshness,  # 重要性 × 新鲜度
        reverse=True
    )
    return sorted_memories[:20]  # Top 20
```

**Phase 2（M7+，任务感知检索）**：
```python
def _render_phase2(self):
    intent = self.planner.plan(current_task)
    results = self.retrieval_engine.retrieve(intent)
    return results[:10]  # Top 10 最相关的
```

输出格式：

```xml
<memory-context>
  <memory type="decision" importance="0.9">
    选择 FastAPI 而不是 Flask，因为需要异步支持
  </memory>
  <memory type="tool" importance="0.6">
    使用 alembic 做数据库迁移
  </memory>
</memory-context>
```

---

## 9.3 MemoryCollector：M4 选择管线适配器

```
📁 src/memory/collector.py
```

`MemoryCollector` 实现 `Collector` ABC，让记忆参与 M4 的 Selection Pipeline（Collect → Rank → Select → Pack）。

```python
# SelectionPipeline 的 collectors 列表
collectors = [
    InstructionCollector(),
    WorkspaceCollector(),
    MemoryCollector(memory_core),  # ← 记忆作为一个候选来源
    FileCacheCollector(),
    ConversationCollector(),
]
```

在 M4 的选择管线中，记忆的优先级是 2（排在 instruction=0、workspace=1 之后，file_cache=3、conversation=4 之前）。

---

## 9.4 一句话总结第九章

**Memory OS 通过 MemoryLayer（桥接 BaseLayer）和 MemoryCollector（桥接 M4 Selection Pipeline）将自己插入 Context OS，让记忆自动出现在发给大模型的 Prompt 中。**

---

# 第十章：Agent 可用的 16 个工具

## 10.1 工具一览

```
📁 src/memory/tools.py
```

| 工具 | 类别 | 功能 |
|------|------|------|
| `memory_add` | 写入 | 添加记忆（→ Pipeline → Store） |
| `memory_get` | 读取 | 按 ID 读取记忆 |
| `memory_list` | 读取 | 按类型/状态列出记忆 |
| `memory_update` | 写入 | 更新记忆字段 |
| `memory_delete` | 写入 | 软删除记忆 |
| `memory_search` | 检索 | 混合检索（M7） |
| `memory_feedback` | 评分 | 显式反馈（M8） |
| `memory_extract` | 智能 | 手动触发知识提取（M9） |
| `memory_reflect` | 智能 | 手动触发反思（M9） |
| `memory_conflicts` | 智能 | 列出冲突记忆（M9） |
| `memory_resolve` | 智能 | 手动解决冲突（M9） |
| `memory_archive` | 生命周期 | 手动归档（M10） |
| `memory_restore` | 生命周期 | 恢复已归档记忆（M10） |
| `memory_compress` | 生命周期 | 手动压缩一组记忆（M10） |
| `memory_stats` | 可观测 | 记忆库统计信息 |
| `memory_purge` | 生命周期 | 硬删除（不可恢复） |

---

## 10.2 工具示例

### memory_add

```python
# Agent 决定记住一个重要信息
memory_add(
    type="decision",
    content="整个项目统一使用 Pydantic v2 做数据校验，不要用 v1",
    tags=["pydantic", "validation", "standard"],
    scope="project",
    importance=0.85,
)
```

### memory_search

```python
# Agent 需要查找关于认证的记忆
memory_search(
    query="用户认证 token 刷新",
    types=["decision", "tool"],  # 只看决策和工具
    max_results=5,
)
```

### memory_feedback

```python
# Agent 发现一条记忆没用
memory_feedback(
    memory_id="abc123",
    rating="not_useful",
)
```

### memory_compress

```python
# Agent 主动要求压缩一组记忆
memory_compress(
    type_filter="tool",     # 只看工具类
    tag_filter="pytest",    # 只看 pytest 相关的
    strategy="hybrid",      # 混合策略（规则+LLM）
)
```

---

## 10.3 一句话总结第十章

**Agent 通过 16 个工具与 Memory OS 交互，覆盖了增删改查、智能检索、反馈学习、反思清理的全部能力。**

---

# 第十一章：完整架构回顾

## 11.1 从对话到记忆的完整循环

```
用户: "给 auth.py 加刷新 token 功能"
      │
      ▼
Agent Loop 开始工作
      │
      ├─→ M7 Context Engine (MemoryLayer.render())
      │   自动检索相关记忆：
      │   "之前选择 JWT 而不是 Session" (DECISION)
      │   "用 python-jose 做 JWT 加解密" (TOOL)
      │   "用户要求 token 有效期 30min" (USER)
      │   → 这些记忆出现在 Prompt 中
      │
      ├─→ Agent 完成任务（修改了 auth.py）
      │
      ├─→ M9 TriggerPolicy: TASK_END 触发
      │   KnowledgeExtractor 从对话中学习：
      │   "新增候选记忆: auth.py 实现了 refresh_token 接口..."
      │   → Validator → Pipeline → 写入 Store
      │
      ├─→ M7 EmbeddingWorker 异步构建语义索引
      │
      ├─→ M8 ImportanceScorer 给新记忆打分
      │
      └─→ Agent 返回结果给用户
```

## 11.2 完整的文件地图

```
src/memory/                          (Memory OS 根目录)
├── __init__.py                      ← MemoryCore 门面（M6）
├── types.py                         ← MemoryEntry 数据模型（M6）
├── identity.py                      ← 6 种 ID 类型（M6）
├── events.py                        ← 事件总线（M6）
├── schema.py                        ← Schema 校验/迁移（M6）
├── index.py                         ← 5 种倒排索引（M6）
├── policy.py                        ← 7 种规则插件（M6）
├── pipeline.py                      ← 5 阶段处理管线（M6）
├── registry.py                      ← 类型注册中心（M6）
├── metadata.py                      ← 解耦扩展存储（M6）
├── store.py                         ← 三池纯存储（M6）
├── layer.py                         ← Context OS 桥接层（M6）
├── collector.py                     ← M4 Selection 适配器（M6）
├── tools.py                         ← 16 个 Agent 工具（M6-M10）
├── retrieval/                       ← M7 检索引擎
│   ├── engine.py                    ← 检索引擎门面
│   ├── retriever.py                 ← Keyword/Vector/Recent 检索器
│   ├── hybrid.py                    ← 混合融合策略
│   ├── ranker.py                    ← 二次排序器
│   ├── planner.py                   ← 任务感知检索规划
│   ├── pipeline.py                  ← 检索管线
│   ├── vector_index.py              ← 向量索引（NumPy）
│   ├── embedding_index.py           ← Embedding→Store 桥接
│   ├── embedding_worker.py          ← 异步 Embedding
│   ├── query.py                     ← 查询/结果类型
│   └── config.py                    ← 检索配置
├── importance/                      ← M8 重要性引擎
│   ├── engine.py                    ← 重要性引擎门面
│   ├── scoring.py                   ← 评分器
│   ├── decay.py                     ← 指数衰减
│   ├── tracking.py                  ← 访问追踪
│   ├── feedback.py                  ← 反馈处理
│   ├── vacuum.py                    ← 低价值检测
│   └── config.py                    ← 重要性配置
├── intelligence/                    ← M9 智能引擎
│   ├── engine.py                    ← 智能引擎门面
│   ├── extractor.py                 ← 知识提取器
│   ├── reflector.py                 ← 反思引擎
│   ├── trigger.py                   ← 触发策略
│   ├── worker.py                    ← 异步工作线程
│   ├── validator.py                 ← 候选校验器
│   ├── parser.py                    ← 响应解析器
│   ├── prompt_loader.py             ← Prompt 模板加载器
│   ├── candidate.py                 ← 候选记忆类型
│   ├── relation_types.py            ← 关系类型枚举
│   ├── prompts/                     ← Prompt 模板目录
│   │   ├── extract_system.md
│   │   ├── extract_user.md
│   │   ├── merge_system.md
│   │   ├── merge_user.md
│   │   ├── conflict_system.md
│   │   ├── conflict_user.md
│   │   ├── refine_system.md
│   │   ├── refine_user.md
│   │   ├── split_system.md
│   │   └── split_user.md
│   ├── strategies/                  ← 反思策略
│   │   ├── base.py                  ← 策略 ABC
│   │   ├── merge.py                 ← 合并策略
│   │   ├── conflict.py              ← 冲突检测策略
│   │   ├── refine.py                ← 细化策略
│   │   └── split.py                 ← 拆分策略
│   └── config.py                    ← 智能配置
└── lifecycle/                       ← M10 生命周期引擎
    ├── engine.py                    ← 生命周期引擎门面
    ├── manager.py                   ← 状态转移管理（M6）
    ├── state.py                     ← 状态机
    ├── policy.py                    ← 策略引擎
    ├── archiver.py                  ← 自动归档
    ├── compressor.py                ← 记忆压缩
    ├── gc.py                        ← 垃圾回收
    ├── worker.py                    ← 后台调度
    ├── metrics.py                   ← 健康指标
    └── config.py                    ← 生命周期配置
```

## 11.3 核心数据流总结

```
记忆写入流:
  Agent → memory_add → MemoryEntry.create()
  → Pipeline (Schema → Normalize → Deduplicate → PolicyCheck → Persist)
  → Store.active
  → EventBus.emit(CREATED)
  → M7 EmbeddingWorker (异步) → VectorIndex
  → M8 ImportanceScorer → 自动评分

记忆检索流:
  Agent → memory_search / MemoryLayer.render()
  → M7 MemoryPlanner.plan(task) → RetrievalIntent
  → HybridRetriever (Keyword + Vector + Recent)
  → WeightedSumFusion / RRF
  → Reranker (relevance × importance × freshness × frequency)
  → Top-K 结果
  → EventBus.emit(ACCESSED) → M8 AccessTracker

记忆维护流:
  M10 LifecycleWorker (后台定时)
  → ArchiveEngine (COLD → ARCHIVED)
  → GarbageCollector (清理/验证/修复)
  → MemoryCompressor (压缩同类记忆)
  → 健康指标更新
```

---

# 第十二章：与 Context Engine 的关系

## 12.1 两个系统的职责边界

| 维度 | Context Engine | Memory OS |
|------|---------------|-----------|
| 管理对象 | 当前对话的上下文（临时的） | 跨对话的知识（持久的） |
| 生命周期 | 一次对话 | 永久（直到被清理） |
| 主要操作 | 收集→排序→选择→打包 | 写入→索引→检索→评分→清理 |
| 输出 | 发给 LLM 的 Prompt | 检索结果 / 上下文片段 |
| 存储 | Store（KV 键值） | MemoryStore（三池 + 索引） |

**一句话区分**：Context Engine 管理"现在这轮对话需要什么"，Memory OS 管理"过去学到了什么"。

---

## 12.2 两个系统的集成点

```
Context Engine                         Memory OS
─────────────                         ─────────
ContextOrchestrator
  │
  ├─ register_layer(memory_layer) ──→ MemoryLayer (BaseLayer)
  │                                   render() → 检索记忆 → 格式化输出
  │
  ├─ build_prompt()                   SelectionPipeline
  │   └─ SelectionPipeline                │
  │       └─ MemoryCollector ←────────────┘
  │           collect() → MemoryCandidate
  │           → Rank → Select → Pack
  │
  └─ PromptBuilder ←─ 最终 Prompt 中包含 <memory-context>
```

**关键原则**：Memory OS 不 import Context OS 内部模块，Context OS 不 import Memory OS。唯一的接触点是 `MemoryLayer` 继承 `BaseLayer`（Python 标准继承，无直接 import）。

---

## 12.3 一句话总结第十二章

**Context Engine 是"当前这次对话的管家"，Memory OS 是"所有对话的知识库"。两者通过 MemoryLayer 和 MemoryCollector 优雅地连接，互不污染。**

---

# 附录 A：快速上手

## A.1 启动 Memory OS

```python
from pathlib import Path
from src.memory import MemoryCore, MemoryEntry, MemoryType

# 1. 创建 Memory Core
core = MemoryCore(db_path=Path(".memory"))

# 2. 恢复之前的记忆
count = core.load()
print(f"加载了 {count} 条记忆")

# 3. 初始化 M7 检索引擎
core.init_retrieval()

# 4. 初始化 M8 重要性引擎
core.init_importance()

# 5. 添加一条记忆
entry = MemoryEntry.create(
    text="使用 ruff 代替 flake8 做代码检查",
    type=MemoryType.TOOL,
    tags=["linting", "ruff", "python"],
    importance=0.7,
)
ok, reason, result = core.add(entry)
print(f"添加结果: {ok}, {reason}")

# 6. 搜索记忆
from src.memory import RetrievalQuery
results = core.retrieval.retrieve(RetrievalQuery(text="代码检查工具"))
for r in results[:5]:
    print(f"  [{r.score:.2f}] {r.entry.content.summary}")

# 7. 保存
core.save()
```

## A.2 接入 Context Engine

```python
from src.memory.layer import MemoryLayer
from src.memory.collector import MemoryCollector

# 创建 MemoryLayer 桥接
memory_layer = MemoryLayer(core)

# 注册到 ContextOrchestrator
orchestrator.register_layer(memory_layer, position=2)

# 记忆会自动出现在 build_prompt() 的输出中
```

## A.3 启用智能学习（M9）

```python
# 初始化 M9（依赖 M7 和 M8）
core.init_intelligence(llm_call=my_llm_function)

# 初始化 M10（依赖 M7）
core.init_lifecycle(llm_call=my_llm_function)

# 触发一次知识提取
core.intelligence.extract_from_conversation(messages)

# 手动运行反思
core.intelligence.reflection_engine.run()
```

---

# 附录 B：常见问题

**Q: M7 的 Embedding 接口是什么？**
A: 默认使用一个兼容 OpenAI Embedding API 的接口。实现 `DenseEmbedder` 协议即可替换。

**Q: 如果 Embedding 服务挂了，影响写入吗？**
A: 不影响。写入流程（Pipeline → Store）在 Embedding 之前就完成了。Embedding Worker 失败只是暂时少了语义检索能力，关键词检索仍然可用。恢复后 Worker 会自动补全缺失的 Embedding。

**Q: Pipeline 中一个阶段失败，后面的还执行吗？**
A: 不执行。Pipeline 是短路模式——任一阶段返回 `accepted=False`，后续阶段跳过，原因返回给调用者。

**Q: 硬删除（purge）后能恢复吗？**
A: 不能。purge 是物理删除——从 Store、Index、Metadata、VectorIndex 中全部移除。这是不可逆操作。

**Q: M9 的 LLM 幻觉怎么防？**
A: 三层防御：① CandidateValidator 校验格式和语义重复 ② Pipeline 五道关卡（同 memory_add）③ M8 ImportanceEngine 给 LLM 提取的记忆更低的基础 source_weight（0.7 vs 用户手动的 1.0）。

**Q: 记忆太多怎么办？**
A: 三层机制：① M8 Vacuum 检测低价值记忆 ② M10 ArchiveEngine 定期归档冷记忆 ③ M10 MemoryCompressor 压缩同类记忆。系统会自动保持记忆库在健康规模。

---

# 附录 C：术语速查表

| 术语 | 英文 | 一句话解释 |
|------|------|-----------|
| 记忆 | Memory | 跨对话保留的知识 |
| 管道 | Pipeline | 写入前的多道关卡 |
| 三池 | Three-Pool | Active / Archived / Deleted |
| 事件总线 | Event Bus | 发布/订阅通信系统 |
| 规则引擎 | Policy Engine | 可插拔的规则检查 |
| 倒排索引 | Inverted Index | "值→ID"的快速查找 |
| 混合检索 | Hybrid Retrieval | 关键词+语义+最近联合搜索 |
| 融合 | Fusion | 多通道结果的合并算法 |
| 二次排序 | Rerank | 用更多因素重新排序 |
| 嵌入 | Embedding | 文字→向量，让语义可计算 |
| 向量索引 | Vector Index | 高效最近邻搜索 |
| 指数衰减 | Exponential Decay | 记忆随时间自然贬值 |
| 重要性 | Importance | 记忆的综合价值分数 |
| 新鲜度 | Freshness | 记忆的新鲜程度 |
| 反馈 | Feedback | 用户/Agent 的显式评价 |
| 知识提取 | Knowledge Extraction | 从对话中自动提取记忆 |
| 反思 | Reflection | 定期审查已有的记忆 |
| 策略 | Strategy | 可插拔的处理算法 |
| 触发器 | Trigger | 自动学习的启动条件 |
| 建议者模式 | Proposer-Authority | LLM 提议、系统把关 |
| 状态机 | State Machine | 管理记忆的 5 种状态转移 |
| 归档 | Archive | 冷记忆的"冷冻保存" |
| 压缩 | Compression | 多条记忆合并为一条 |
| 垃圾回收 | GC | 清理/验证/修复记忆库 |
| 门面 | Facade | 统一入口，隐藏内部复杂性 |
| 桥接层 | Bridge Layer | 让 Memory OS 兼容 Context OS |

---

> **全文完。**  
>   
> 这篇教材覆盖了 Memory OS 从 M6 到 M10 的全部内容：从最基础的三池存储，到异步 Embedding 的语义检索，到事件驱动的自动评分，到 LLM 辅助的知识提取与反思，再到后台的自动归档、压缩和垃圾回收。  
>   
> 配合 `docs/context-engine-textbook.md`，你就能完整理解 agent-core 的两大操作系统：Context OS（管理"现在"）和 Memory OS（管理"过去"）。
