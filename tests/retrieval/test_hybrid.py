"""Tests for loom.retrieval.hybrid — combined score and context builder."""

import pytest

from loom.retrieval.hybrid import HybridResult, _combined_score
from loom.retrieval.context_builder import build_context


class TestCombinedScore:
    """Test the ranking formula."""

    def test_vector_only_hit(self) -> None:
        score = _combined_score(vector_score=0.9, graph_hops=0)
        assert score == pytest.approx(0.54)  # 0.9 * 0.6

    def test_graph_only_hit(self) -> None:
        score = _combined_score(vector_score=0.0, graph_hops=1)
        assert score == pytest.approx(0.4)  # 0.4 * (1/1)

    def test_graph_depth_2(self) -> None:
        score = _combined_score(vector_score=0.0, graph_hops=2)
        assert score == pytest.approx(0.2)  # 0.4 * (1/2)

    def test_combined_vector_and_graph(self) -> None:
        # This shouldn't happen normally (a result is either vector or graph)
        # but the formula should still work
        score = _combined_score(vector_score=0.8, graph_hops=1)
        assert score == pytest.approx(0.88)  # 0.8*0.6 + 0.4*1

    def test_high_vector_beats_distant_graph(self) -> None:
        vector = _combined_score(0.9, 0)
        graph = _combined_score(0.0, 2)
        assert vector > graph

    def test_close_graph_beats_low_vector(self) -> None:
        graph = _combined_score(0.0, 1)
        vector = _combined_score(0.3, 0)
        assert graph > vector


class TestHybridResult:
    """Test HybridResult dataclass."""

    def test_defaults(self) -> None:
        r = HybridResult(
            path="test.md", score=0.5, vector_score=0.5,
            graph_hops=0, excerpt="hello",
        )
        assert r.metadata == {}

    def test_with_metadata(self) -> None:
        r = HybridResult(
            path="test.md", score=0.5, vector_score=0.5,
            graph_hops=0, excerpt="hello",
            metadata={"project": "loom"},
        )
        assert r.metadata["project"] == "loom"


class TestBuildContext:
    """Test context_builder.build_context formatting."""

    def _make_result(
        self,
        path: str = "test.md",
        score: float = 0.9,
        graph_hops: int = 0,
        excerpt: str = "Some content here.",
        metadata: dict | None = None,
    ) -> HybridResult:
        return HybridResult(
            path=path, score=score, vector_score=score,
            graph_hops=graph_hops, excerpt=excerpt,
            metadata=metadata or {},
        )

    def test_empty_results(self) -> None:
        output = build_context([])
        assert "No relevant context found" in output

    def test_single_result_formatted(self) -> None:
        results = [self._make_result()]
        output = build_context(results)
        assert "## Relevant Context from Vault" in output
        assert "test.md" in output
        assert "Some content here" in output

    def test_includes_score(self) -> None:
        results = [self._make_result(score=0.92)]
        output = build_context(results)
        assert "0.92" in output

    def test_graph_result_labeled(self) -> None:
        results = [self._make_result(graph_hops=2)]
        output = build_context(results)
        assert "via graph" in output

    def test_vector_result_labeled(self) -> None:
        results = [self._make_result(graph_hops=0)]
        output = build_context(results)
        assert "vector" in output

    def test_metadata_tags_shown(self) -> None:
        results = [self._make_result(metadata={"tags": ["auth", "jwt"]})]
        output = build_context(results)
        assert "auth" in output
        assert "jwt" in output

    def test_token_budget_limits_results(self) -> None:
        results = [
            self._make_result(path=f"note{i}.md", excerpt="x" * 500)
            for i in range(20)
        ]
        output = build_context(results, token_budget=200)
        # Should not include all 20 results
        assert output.count("###") < 20

    def test_always_includes_at_least_one_result(self) -> None:
        results = [self._make_result(excerpt="x" * 2000)]
        output = build_context(results, token_budget=10)
        assert "test.md" in output

    def test_result_count_in_footer(self) -> None:
        results = [self._make_result(), self._make_result(path="b.md")]
        output = build_context(results)
        assert "results" in output
        assert "tokens" in output
