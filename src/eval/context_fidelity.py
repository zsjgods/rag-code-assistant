"""Context Fidelity Evaluation — 测试 Agent 长对话压缩后的目标保持能力。

核心理念：
  不是测 LLM 的工具调用能力（那是 BFCL 的活），而是测 agent-core 框架
  的上下文压缩模块在长对话场景下是否会导致目标丢失、关键信息遗忘。

与 BFCL/GAIA 的区别：
  - BFCL: 单轮 API 调用，不经过 agent 主循环 → 测 LLM 裸能力
  - GAIA: 多轮但不触发压缩 → 测 LLM+工具整体
  - Context Fidelity: 多轮+强制压缩+插干扰 → 测 agent-core 框架

评测设计：
  模拟真实 Agent 使用场景：用户给一个初始目标，中间经历多轮对话、
  大量工具调用、干扰性问题，触发多轮压缩。最终检查 Agent 是否仍能
  准确记住原始目标、关键约束、中间决策。

三层指标：
  1. Goal Fidelity      — 压缩后是否还记得原始目标（不扭曲、不丢失）
  2. Constraint Recall   — 目标中的约束条件是否保留（"只要Python文件"等）
  3. Decision Trace      — 中间关键决策是否在压缩后仍可回溯
"""

# ═══════════════════════════════════════════════════════════════
#  测试场景设计 (Test Scenarios)
# ═══════════════════════════════════════════════════════════════

SCENARIOS = [
    # ── 场景 1: 目标保持 — 简单但长 ─────────────────────
    {
        "id": "goal_fidelity_1",
        "name": "长对话后的目标保持",
        "description": """
用户目标：在项目中找到所有认证相关的代码，分析安全漏洞，生成报告。
中间插入 15 轮不相关对话：问天气、问代码风格、问部署流程、问测试覆盖率等。
经过 3 轮压缩后，问 Agent "你还记得我最初让你做什么吗？"
        """,
        "initial_objective": (
            "找到代码中所有与认证（authentication）相关的模块，"
            "分析每个模块是否存在安全漏洞（硬编码密码、缺失 token 校验、"
            "SQL 注入等），最后生成一份 Markdown 安全审计报告。"
        ),
        "distractions": [
            "帮我查一下今天北京天气怎么样",
            "Python 的 dataclass 和普通 class 有什么区别",
            "这个项目的测试覆盖率有多少",
            "Docker 构建的时候经常报权限错误怎么解决",
            "帮我创建一个 todo：重构 user_service.py 的认证逻辑",
            "redis 连接池的最佳实践是什么",
            "看一下 settings.json 里有什么配置",
            "我们用的是 pytest 还是 unittest",
            "git rebase 和 merge 选哪个好",
            "帮我写一个 CI pipeline 的模板",
            "这个项目用了哪些第三方库",
            "Kubernetes 的 pod 一直 CrashLoopBackOff 怎么排查",
            "设计模式里策略模式和工厂模式哪个更适合支付系统",
            "帮我搜一下 grpc vs rest 性能对比的资料",
            "最近一次 commit 的 diff 是什么",
        ],
        "check": {
            "type": "goal_recall",
            "prompt": "回过头来看，我最初让你做什么？请完整复述我的原始需求。",
            "expected_keywords": [
                "认证", "authentication",
                "安全漏洞", "security",
                "报告", "report",
                "硬编码密码", "token", "SQL 注入",
            ],
            "min_keywords": 3,
        },
    },

    # ── 场景 2: 约束保持 — 有精确约束条件 ───────────────
    {
        "id": "constraint_recall_1",
        "name": "精确约束条件保持",
        "description": """
用户目标：重构 user_service.py，但带了精确约束。
中间插入多轮工具调用和干扰，压缩后检查约束是否还记得。
        """,
        "initial_objective": (
            "重构 src/user_service.py 的 authenticate 方法，要求：\n"
            "1. 只能使用 async/await 异步模式\n"
            "2. 不引入任何新的第三方依赖\n"
            "3. 保持向后兼容（现有 API 签名不变）\n"
            "4. 单元测试覆盖率不能下降\n"
            "这是生产环境的关键路径，需要谨慎处理。"
        ),
        "distractions": [
            "grep 搜一下项目里所有 TODO 注释",
            "看看 scratchpad/notes.txt 有没有之前的重构记录",
            "异步 Python 的 event loop 阻塞了怎么调试",
            "帮我列举一下当前的任务列表",
            "read_file 看一下 src/config.py 的数据库配置",
            "这个错误 'coroutine was never awaited' 是什么意思",
            "帮我加载 'simplify' skill 看看代码简化指南",
            "glob 找出所有 *_service.py 文件",
            "pytest 的 fixture scope 有哪些选项",
        ],
        "check": {
            "type": "constraint_recall",
            "prompt": "关于重构 user_service.py，我之前提了几个约束条件。"
                      "请列出你还记得的所有约束。",
            "expected_keywords": [
                "async/await", "异步",
                "第三方依赖", "不引入",
                "向后兼容", "API 签名",
                "测试覆盖率",
                "生产环境",
            ],
            "min_keywords": 4,
        },
    },

    # ── 场景 3: 决策回溯 — 需要引用之前的中间结果 ───────
    {
        "id": "decision_trace_1",
        "name": "中间决策回溯",
        "description": """
用户做了多步操作后（搜文件→读文件→改文件），中间触发压缩，
然后用户问"为什么你之前选了那个文件修改"，Agent 需要回溯决策链。
        """,
        "initial_objective": (
            "帮我修复项目中所有 Python 文件的 import 顺序问题："
            "先标准库、再第三方库、最后本地模块，每组之间空一行。"
            "从 src/ 目录开始。"
        ),
        "distractions": [
            "glob src/**/*.py 找所有 Python 文件",
            "grep '^import|^from' 在每个找到的文件里搜 import",
            "read_file 读 src/agent/loop.py 的前 50 行",
            "我发现 loop.py 的 import 顺序确实有问题",
            "edit_file 修改 loop.py 的 import 顺序",
            "等等，这个文件还有类型注解缺失的问题，帮我看看",
            "算了先不管类型注解，继续修其他文件的 import",
            "grep 再搜一轮看看有没有遗漏的 import 问题",
            "那个 logger 的 import 好像重复了",
        ],
        "check": {
            "type": "decision_trace",
            "prompt": "我们刚才的修复过程中，你是先看了哪个文件，为什么从那个文件开始？"
                      "整个修复流程是怎样的？",
            "expected_keywords": [
                "loop.py",
                "glob", "搜索",
                "import", "顺序",
                "标准库", "第三方", "本地",
                "grep",
            ],
            "min_keywords": 3,
        },
    },

    # ── 场景 4: 多目标切换 — 同时跟踪多个目标 ───────────
    {
        "id": "multi_objective_1",
        "name": "多目标并行跟踪",
        "description": """
用户同时给了两个独立目标，中间交替处理，触发压缩后检查两个目标是否都保持。
        """,
        "initial_objective": (
            "我有两个并行任务需要你做：\n"
            "任务 A：找出所有 API 端点，检查是否有 Rate Limiting，没有的加上 TODO 注释。\n"
            "任务 B：列出所有使用 SQL 字符串拼接的地方，标记为安全风险。\n"
            "两个任务彼此独立，但都需要扫描整个代码库。"
        ),
        "distractions": [
            "先做任务 A，glob 找所有带 @app.route 或 @router 的文件",
            "grep 'def (get|post|put|delete|patch)' 找 API 函数",
            "看看 src/middleware/rate_limit.py 已有的限流逻辑",
            '切换到任务 B，grep "f\\"SELECT|f\\"INSERT|f\\"UPDATE|f\\"DELETE" 找 SQL 拼接',
            "read_file 看 src/db/query_builder.py 的查询构建方式",
            "不对，pyformat 参数化查询是安全的，排除 query_builder.py",
            "回到任务 A，那些没有 @rate_limit 装饰器的端点都标上了吗",
            "帮我创建一个任务 C：检查所有 API 是否有输入校验",
            "先不管任务 C，继续把任务 A 和 B 收尾",
        ],
        "check": {
            "type": "multi_objective",
            "prompt": "我给了你两个并行任务 A 和 B，分别是什么？各自进度如何？",
            "expected_keywords": [
                "Rate Limiting", "限流", "API",
                "SQL", "字符串拼接", "安全风险",
                "TODO", "标记",
                "代码库", "扫描",
            ],
            "min_keywords": 4,
        },
    },

    # ── 场景 5: 长对话下的 scratchpad 持久化 ─────────────
    {
        "id": "scratchpad_persistence_1",
        "name": "Scratchpad 跨压缩持久化",
        "description": """
Agent 把关键信息写入 scratchpad，中间触发多轮压缩，
检查 scratchpad 中的信息是否仍然可读且完整。
        """,
        "initial_objective": (
            "帮我做一次完整的代码审查（Code Review），"
            "重点检查：错误处理、资源泄露、并发安全。"
            "审查过程中发现的每个问题都记录到 scratchpad/review_findings.txt。"
        ),
        "distractions": [
            "glob src/**/*.py 了解项目结构",
            "read_file src/bus/message_bus.py 看看消息总线的错误处理",
            "我发现 message_bus.py 的 except 块吞掉了所有异常，记到 scratchpad",
            "read_file src/agent/loop.py 看主循环的并发处理",
            "loop.py 里有个共享状态没有加锁，记到 scratchpad",
            "对了，你说的资源泄露具体指什么",
            "就是文件句柄没关、数据库连接没回收、内存没释放这些",
            "read_file src/tools/builtin/__init__.py 看看工具有没有关闭资源",
            "写得太久了，先把目前发现的问题汇总一下",
        ],
        "check": {
            "type": "scratchpad_check",
            "prompt": "读一下 scratchpad/review_findings.txt，列出你到目前为止发现的所有问题。",
            "required_tools": ["scratchpad_read"],
            "expected_keywords": [
                "message_bus", "异常",
                "loop.py", "共享状态", "锁",
                "资源", "泄露",
                "错误处理",
            ],
            "min_keywords": 3,
        },
    },
]


# ═══════════════════════════════════════════════════════════════
#  评分方法 (Scoring Methodology)
# ═══════════════════════════════════════════════════════════════

SCORING = """
每个场景的评分标准：

Goal Fidelity Score (0-100):
  - 100: 完整复述目标，所有关键要素都在
  - 70:  核心目标正确，但遗漏了 1-2 个次要约束
  - 40:  目标部分正确，但遗漏了关键约束或混入了无关内容
  - 0:   目标完全错误或遗忘

Constraint Recall Rate:
  - 原始约束中，压缩后还能回忆起的比例 (expected_keywords 命中率)

Decision Trace Score (0-100):
  - 100: 完整回溯决策链，包括中间步骤和推理依据
  - 70:  主要步骤正确，但遗漏了中间跳转
  - 40:  只能回忆最近的 1-2 步
  - 0:   无法回溯决策过程

Overall Context Fidelity:
  - 所有场景的加权平均分
  - Goal Fidelity × 0.4 + Constraint Recall × 0.3 + Decision Trace × 0.3
"""


# ═══════════════════════════════════════════════════════════════
#  评测流程
# ═══════════════════════════════════════════════════════════════

EVALUATION_PROTOCOL = """
1. 设定初始目标 → Agent 开始执行
2. 每 3 轮对话插入一次干扰（问不相关的、调无关工具）
3. 累积到 ~15 轮时，agent-core 的压缩模块应该被触发
4. 累计 3 次压缩后，发送 "check prompt"
5. LLM Judge 评估 Agent 的回答：
   - 关键词命中率（命中数 / 期望数）
   - 目标完整性（1-5 分）
   - 是否有幻觉插入（负分项）
6. 每个场景跑 3 次取平均（消除 LLM 随机性）

对比实验：
  - 开启压缩 vs 关闭压缩（控制变量）
  - 不同 LLM 的对比（同一个 agent 框架）
"""
