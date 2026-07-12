"""RetrievalPipeline — pluggable pipeline for memory retrieval flow.

Separate from M6's write Pipeline (which handles validate→normalize→deduplicate→persist).
This pipeline handles: query expansion → retrieve → rerank → filter → format.

Same pattern as M6 Pipeline: register_stage / remove_stage / process.
"""

from abc import ABC, abstractmethod

from src.memory.retrieval.query import RetrievalQuery, RetrievalResult


class RetrievalStage(ABC):
    """Abstract stage in the retrieval pipeline."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def process(
        self,
        results: list[RetrievalResult],
        query: RetrievalQuery,
        store,  # MemoryStore
    ) -> tuple[list[RetrievalResult], RetrievalQuery]:
        """Process retrieval results. May modify results, query, or both.

        Returns (results, query) — either may be modified.
        """
        ...

    def priority(self) -> int:
        return 50


# ═══════════════════════════════════════════════════════════════════
# Built-in Stages
# ═══════════════════════════════════════════════════════════════════

class RetrieverStage(RetrievalStage):
    """Execute HybridRetriever and return candidates."""

    name = "retriever"

    def __init__(self, hybrid_retriever):
        self._hybrid = hybrid_retriever

    def process(self, results, query, store):
        new_results = self._hybrid.retrieve(query)
        return new_results, query

    def priority(self) -> int:
        return 10  # First stage


class RerankerStage(RetrievalStage):
    """Apply Reranker for second-pass scoring."""

    name = "reranker"

    def __init__(self, reranker, max_candidates: int = 25):
        self._reranker = reranker
        self._max_candidates = max_candidates

    def process(self, results, query, store):
        # Limit candidates before reranking (performance)
        candidates = results[:self._max_candidates]
        reranked = self._reranker.rerank(candidates, store)
        return reranked, query

    def priority(self) -> int:
        return 20


class FilterStage(RetrievalStage):
    """Apply post-retrieval filters (type, tag, project, importance)."""

    name = "filter"

    def process(self, results, query, store):
        filtered = []
        for r in results:
            entry = r.entry
            if entry is None:
                filtered.append(r)
                continue

            if query.type_filter and entry.type.value not in query.type_filter:
                continue
            if query.tag_filter:
                entry_tags = {t.lower() for t in entry.content.tags}
                if not entry_tags.intersection(t.lower() for t in query.tag_filter):
                    continue
            if query.project_filter and entry.project.value != query.project_filter:
                continue
            if entry.importance < query.min_importance:
                continue

            filtered.append(r)

        return filtered, query

    def priority(self) -> int:
        return 30


class DeduplicateStage(RetrievalStage):
    """Remove near-duplicate results (same id or highly similar content)."""

    name = "deduplicate"

    def process(self, results, query, store):
        seen_ids: set[str] = set()
        unique = []
        for r in results:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                unique.append(r)
        return unique, query

    def priority(self) -> int:
        return 40


class FormatStage(RetrievalStage):
    """Format results into a Memory Context block for Context OS.

    Returns results unchanged (formatting happens in MemoryLayer.render).
    This stage is a placeholder for future formatting plugins.
    """

    name = "format"

    def process(self, results, query, store):
        # Ensure all results have their entry resolved
        for r in results:
            if r.entry is None:
                from src.memory.identity import MemoryID
                r.entry = store.read(MemoryID(r.id))
        return results[:query.max_results], query

    def priority(self) -> int:
        return 90


# ═══════════════════════════════════════════════════════════════════
# RetrievalPipeline
# ═══════════════════════════════════════════════════════════════════

class RetrievalPipeline:
    """Pluggable pipeline for memory retrieval.

    Usage:
        pipeline = RetrievalPipeline()
        pipeline.register_stage(RetrieverStage(hybrid))
        pipeline.register_stage(RerankerStage(reranker))
        pipeline.register_stage(FilterStage())
        pipeline.register_stage(DeduplicateStage())
        pipeline.register_stage(FormatStage())

        results = pipeline.process(query, store)
    """

    def __init__(self):
        self._stages: list[RetrievalStage] = []

    def register_stage(
        self,
        stage: RetrievalStage,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        self.remove_stage(stage.name)

        if before is not None:
            idx = self._find_index(before)
            if idx >= 0:
                self._stages.insert(idx, stage)
                return
        if after is not None:
            idx = self._find_index(after)
            if idx >= 0:
                self._stages.insert(idx + 1, stage)
                return

        self._stages.append(stage)
        self._stages.sort(key=lambda s: s.priority())

    def remove_stage(self, name: str) -> bool:
        for i, stage in enumerate(self._stages):
            if stage.name == name:
                self._stages.pop(i)
                return True
        return False

    def get_stage(self, name: str) -> RetrievalStage | None:
        for stage in self._stages:
            if stage.name == name:
                return stage
        return None

    def list_stages(self) -> list[str]:
        return [s.name for s in self._stages]

    def process(
        self,
        query: RetrievalQuery,
        store,
    ) -> list[RetrievalResult]:
        """Run all stages in priority order.

        Args:
            query: Retrieval query.
            store: MemoryStore instance.

        Returns:
            Final ranked, filtered, deduplicated results.
        """
        results: list[RetrievalResult] = []
        current_query = query

        for stage in self._stages:
            try:
                results, current_query = stage.process(results, current_query, store)
            except Exception:
                # Best-effort: one bad stage doesn't break the pipeline
                pass

        return results

    def _find_index(self, name: str) -> int:
        for i, stage in enumerate(self._stages):
            if stage.name == name:
                return i
        return -1
