"""ContextOrchestrator — single entry point for all context operations.

The agent_loop and all external code interact with context ONLY through
this facade. No direct messages[] manipulation, no direct system prompt
construction.

Layer Registry:
    register_layer(layer, position) — add a new layer dynamically
    unregister_layer(name)          — remove a layer
    get_layer(name)                 — look up a layer by name
    iter_layers()                   — list all registered layers

This design means future layers (Memory, Workspace, Scratchpad, etc.)
can be added via register_layer() without modifying this file.

M2: WorkspaceLayer + FileCacheLayer
    Event hooks: on_file_read, on_file_write, on_directory_changed

M3: SummaryLayer + Compression Framework
    BudgetManager (budget), CompressionPolicy (decision), CompressionPipeline (execution)
    tick() — called each agent loop iteration for compression if needed.
"""

from typing import Callable

from src.context.layers.base import BaseLayer
from src.context.layers.instruction import InstructionLayer
from src.context.layers.conversation import ConversationLayer
from src.context.layers.workspace import WorkspaceLayer
from src.context.layers.file_cache import FileCacheLayer
from src.context.layers.summary import SummaryLayer
from src.context.prompt_builder import PromptBuilder
from src.context.types import BuildResult, BudgetConfig
from src.state.store import Store


class ContextOrchestrator:
    """Single facade for context management.

    Owns:
      - Layer registry (dynamic, supports register/unregister)
      - PromptBuilder (assembles layers into final prompt)
      - Store reference (for persistent state like objective, facts)

    Usage:
        orch = ContextOrchestrator(
            store=STORE,
            base_system=SYSTEM,
            skills_descriptions=SKILLS.descriptions(),
        )
        agent_loop(messages, registry, client, orchestrator=orch, ...)
    """

    def __init__(
        self,
        *,
        store: Store | None = None,
        base_system: str = "",
        skills_descriptions: str = "",
        tool_rules: str = "",
        safety_rules: str = "",
        output_rules: str = "",
        budget: BudgetConfig | None = None,
        get_objective_fn: "Callable[[], str] | None" = None,
        get_persistent_fn: "Callable[[], list[str]] | None" = None,
        on_important_fn: "Callable[[str, list[str]], None] | None" = None,

        # M2: Workspace + File Cache
        workspace: WorkspaceLayer | None = None,
        file_cache: FileCacheLayer | None = None,

        # M6: Memory (typed as BaseLayer to avoid context→memory import)
        memory_layer: "BaseLayer | None" = None,

        # M3: Budget + Compression
        budget_manager: "BudgetManager | None" = None,
        compression_policy: "CompressionPolicy | None" = None,
        compression_pipeline: "CompressionPipeline | None" = None,
        summarizer: "Summarizer | None" = None,
        llm_call: "Callable[[str], str] | None" = None,
        circuit_breaker: "CircuitBreaker | None" = None,

        # M4: Context Selection Pipeline (optional)
        selection_pipeline: "SelectionPipeline | None" = None,
    ):
        # ── Store (backing persistence) ─────────────────
        self.store = store or Store()
        self._budget_cfg = budget or BudgetConfig()
        self._on_important = on_important_fn

        # ── M3: Budget + Compression components ──────────
        self._budget_mgr = budget_manager
        self._policy = compression_policy
        self._pipeline = compression_pipeline
        self._summarizer = summarizer
        self._llm_call = llm_call
        self._circuit_breaker = circuit_breaker

        # ── M4: Context Selection Pipeline ───────────────
        self._selection_pipeline = selection_pipeline

        # ── Create default M1 layers ─────────────────────

        # Conversation layer — owns the messages list
        self._conversation = ConversationLayer()

        # Instruction layer — immutable system prompt
        self._instruction = InstructionLayer(
            base_system=base_system,
            skills_descriptions=skills_descriptions,
            tool_rules=tool_rules,
            safety_rules=safety_rules,
            output_rules=output_rules,
            get_objective=get_objective_fn
            or (lambda: self.store.get("current_objective", "")),
            get_persistent=get_persistent_fn
            or (lambda: self.store.get("persistent_facts", [])),
        )

        # ── M2: Workspace + File Cache (optional) ────────
        self._workspace: WorkspaceLayer | None = workspace
        self._file_cache: FileCacheLayer | None = file_cache

        # ── M6: Memory (optional) ──────────────────────────
        self._memory: BaseLayer | None = memory_layer

        # ── M3: SummaryLayer (one per lifecycle) ─────────
        self._summary: SummaryLayer | None = SummaryLayer() if budget_manager else None

        # ── Layer registry (dynamic, for future extension) ─
        self._layers: dict[str, BaseLayer] = {}
        self._layer_order: list[str] = []

        # ── Prompt builder ──────────────────────────────
        self._builder = PromptBuilder(
            total_budget=self._budget_cfg.total_budget,
        )

        # ── Register layers in fixed order ───────────────
        # instruction(0) → [workspace] → [file_cache] → [summary] → conversation(last)
        self.register_layer(self._instruction)
        self.register_layer(self._conversation)

        pos = 1  # insert conditional layers between instruction and conversation
        if self._workspace:
            self.register_layer(self._workspace, position=pos)
            pos += 1
        if self._file_cache:
            self.register_layer(self._file_cache, position=pos)
            pos += 1
        if self._memory:
            self.register_layer(self._memory, position=pos)
            pos += 1
        if self._summary:
            self.register_layer(self._summary, position=pos)

    # ── Layer Registry ──────────────────────────────────

    def register_layer(self, layer: BaseLayer, position: int | None = None) -> None:
        """Register a new context layer.

        If a layer with the same name already exists, it is replaced.

        Args:
            layer: The layer instance to register.
            position: Insertion index in assembly order (None = append).
        """
        # Remove old layer with same name if exists
        self.unregister_layer(layer.name)

        self._layers[layer.name] = layer
        if position is not None:
            self._layer_order.insert(position, layer.name)
        else:
            self._layer_order.append(layer.name)

        self._sync_builder_layers()

    def unregister_layer(self, name: str) -> bool:
        """Remove a layer by name. Returns True if found."""
        if name not in self._layers:
            return False
        del self._layers[name]
        self._layer_order.remove(name)
        self._sync_builder_layers()
        return True

    def get_layer(self, name: str) -> BaseLayer | None:
        """Look up a layer by name."""
        return self._layers.get(name)

    def iter_layers(self) -> list[BaseLayer]:
        """Return all registered layers in assembly order."""
        return [self._layers[name] for name in self._layer_order if name in self._layers]

    def _sync_builder_layers(self) -> None:
        """Sync the prompt builder's layer list with the registry."""
        # Rebuild the builder's layer list in registry order
        self._builder._layers = self.iter_layers()

    # ── Message operations (→ ConversationLayer) ────────

    def add_message(self, role: str, content) -> None:
        """Append a message to the conversation."""
        self._conversation.add_message(role, content)

    def get_messages(self) -> list[dict]:
        """Return the raw messages list (same object, for compression compat)."""
        return self._conversation.get_messages()

    def replace_messages(self, new_messages: list[dict]) -> None:
        """Replace all messages in-place (for compression)."""
        self._conversation.replace_messages(new_messages)

    # ── Prompt building (→ PromptBuilder) ───────────────

    def build_prompt(self) -> BuildResult:
        """Assemble the final prompt from all registered layers.

        M4+ path: when a SelectionPipeline is configured, the prompt is
        built through Collect → Rank → Select → Pack → build_from_package.
        The orchestrator does NOT know about Collector/Ranker/Policy details.

        Legacy path (M1-M3): direct Layer → PromptBuilder iteration.
        """
        if self._selection_pipeline:
            from src.context.selection import SelectionContext

            # Dynamic field mapping — add new layers here for M4 path support
            _field_map = {
                "instruction": "_instruction",
                "conversation": "_conversation",
                "workspace": "_workspace",
                "file_cache": "_file_cache",
                "summary": "_summary",
                "memory": "_memory",  # M6
            }
            ctx = SelectionContext()
            for layer in self.iter_layers():
                attr = _field_map.get(layer.name)
                if attr and hasattr(self, attr):
                    setattr(ctx, layer.name, getattr(self, attr))
            sel_result = self._selection_pipeline.run(ctx)
            result = self._builder.build_from_package(sel_result.package)

            # Observability
            for stat in result.stats:
                print(f"  [context] {stat.layer_name}: {stat.token_count} tokens")
            if sel_result.discarded:
                print(f"  [context] discarded {len(sel_result.discarded)} candidates "
                      f"({sum(c.token_count for c in sel_result.discarded)} tokens)")

            return result

        # Legacy M1-M3 path
        result = self._builder.build()
        for stat in result.stats:
            flag = " ⚠" if stat.is_over_budget else ""
            print(
                f"  [context] {stat.layer_name}: {stat.token_count} tokens "
                f"({stat.budget_used:.0%} of budget){flag}"
            )
        return result

    # ── Persistent state helpers (→ Store) ──────────────

    def set_objective(self, text: str) -> None:
        """Update the current objective (compression-immune)."""
        self.store.set("current_objective", text)

    def add_persistent_fact(self, fact: str) -> None:
        """Add a fact to persistent storage (compression-immune)."""
        items: list[str] = self.store.get("persistent_facts", [])
        items.append(fact)
        # Cap at 10 to avoid unbounded growth
        if len(items) > 10:
            items = items[-10:]
        self.store.set("persistent_facts", items)

    def on_important_event(self, level: str, facts: list[str]) -> None:
        """Handle high-importance events detected during compression.

        Routes to external callback if provided, otherwise handles inline.
        """
        if self._on_important:
            self._on_important(level, facts)
            return

        # Default inline handling
        items: list[str] = self.store.get("persistent_facts", [])
        for f in facts:
            items.append(f"[{level}] {f}")
        if len(items) > 10:
            items = items[-10:]
        self.store.set("persistent_facts", items)
        if level == "goal_declaration" and facts:
            self.store.set("current_objective", facts[0])
        print(f"  [context] persisted {level}: {facts}")

    def add_policy(self, text: str) -> None:
        """Add a dynamic policy rule to the instruction layer."""
        self._instruction.add_policy(text)

    # ── M2 Event hooks (for Agent Loop integration) ───────

    def on_file_read(self, path: str, content: str) -> None:
        """Called after a file is read.

        Updates workspace open-files list and populates file cache.

        Args:
            path: File path that was read.
            content: Full file content returned by the Read tool.
        """
        if self._workspace:
            self._workspace.file_opened(path)
        if self._file_cache:
            self._file_cache.put(path, content)

    def on_file_write(self, path: str) -> None:
        """Called after a file is edited / written.

        Updates workspace modified-files list and invalidates stale cache.

        Args:
            path: File path that was modified.
        """
        if self._workspace:
            self._workspace.file_modified(path)
        if self._file_cache:
            self._file_cache.invalidate(path)

    def on_directory_changed(self, path: str) -> None:
        """Called when the working directory changes.

        Updates workspace CWD and refreshes git state.

        Args:
            path: New working directory path.
        """
        if self._workspace:
            self._workspace.set_cwd(path)

    # ── Public accessors for M2 components ────────────────

    @property
    def workspace(self) -> WorkspaceLayer | None:
        """The registered WorkspaceLayer, or None if not enabled."""
        return self._workspace

    @property
    def file_cache(self) -> FileCacheLayer | None:
        """The registered FileCacheLayer, or None if not enabled."""
        return self._file_cache

    # ── M3: Compression ────────────────────────────────────

    @property
    def has_compression(self) -> bool:
        """Whether M3 compression framework is active."""
        return (
            self._budget_mgr is not None
            and self._policy is not None
            and self._pipeline is not None
        )

    @property
    def summary(self) -> SummaryLayer | None:
        """The registered SummaryLayer, or None if M3 not active."""
        return self._summary

    def tick(self) -> bool:
        """Execute compression pipeline if needed.

        Called once per agent loop iteration (after tool results are appended).
        This is the ONLY entry point for M3 compression.

        Returns:
            True if compression was executed, False if noop.
        """
        if not self.has_compression:
            return False

        # 1. BudgetManager: check all layers
        reports = self._budget_mgr.check(self.iter_layers())

        # 2. Policy: decide if compression is needed
        plan = self._policy.evaluate(reports)
        if plan.action == "noop":
            return False

        # 3. Pipeline: execute compression
        from src.context.compression.pipeline import CompressionContext

        ctx = CompressionContext(
            conversation_messages=self._conversation.get_messages(),
            plan=plan,
            summary=self._summary,
            summarizer=self._summarizer,
            llm_call=self._llm_call,
            circuit_breaker=self._circuit_breaker,
        )
        result = self._pipeline.execute(ctx)

        # 4. Observability (basic print — M5 will replace)
        if ctx.breaker_skipped:
            print(
                f"  [compression] circuit breaker OPEN "
                f"({self._circuit_breaker.failures}/{self._circuit_breaker.max_failures} failures) "
                f"— skipping LLM stages, Tier 1 only"
            )

        for stage in result.stages:
            if stage.skipped:
                continue
            summary_tag = " [summary updated]" if stage.summary_updated else ""
            err_tag = f" ERROR: {stage.error}" if stage.error else ""
            print(
                f"  [compression] {stage.stage_name}: "
                f"{stage.tokens_before} → {stage.tokens_after} tokens "
                f"({stage.duration_ms:.0f}ms){summary_tag}{err_tag}"
            )

        if result.stages:
            print(
                f"  [compression] total: {result.total_tokens_before} → "
                f"{result.total_tokens_after} tokens "
                f"({max(0, result.total_tokens_before - result.total_tokens_after)} saved)"
            )

        return True

    # ── Lifecycle ───────────────────────────────────────

    def clear(self) -> None:
        """Reset all layers. Instruction static parts are preserved."""
        self._conversation.clear()
        self._instruction.clear()
        if self._workspace:
            self._workspace.clear()
        if self._file_cache:
            self._file_cache.clear()
        if self._summary:
            self._summary.clear()

    @property
    def token_count(self) -> int:
        """Total estimated tokens across all layers."""
        return self._builder.estimate_total_tokens()
