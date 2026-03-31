"""Hybrid retrieval — merge vector search with graph expansion and rerank."""

from dataclasses import dataclass, field

from loom.config import LoomConfig
from loom.db import get_connection
from loom.retrieval.chroma_store import ChromaStore
from loom.retrieval.embedder import OllamaEmbedder, OllamaNotAvailableError
from loom.retrieval.graph import VaultGraph
from loom.retrieval.semantic_links import queue_search_links
from loom.vault import VaultClient


@dataclass
class HybridResult:
    """A search result combining vector score and graph distance."""

    path: str
    score: float
    vector_score: float
    graph_hops: int
    excerpt: str
    metadata: dict = field(default_factory=dict)


async def hybrid_search(
    query: str,
    config: LoomConfig,
    project: str | None = None,
    limit: int = 5,
    top_k: int = 20,
    context_note: str | None = None,
) -> list[HybridResult]:
    """Full 3-stage hybrid retrieval pipeline.

    Stage 1: Vector search via ChromaDB
    Stage 2: Graph expansion via BFS on wikilink graph
    Stage 3: Rerank and merge

    When ``config.semantic_links_auto_on_search`` is True and
    ``context_note`` is provided, top-ranked results above the configured
    similarity threshold are queued as pending link suggestions for user
    review via ``loom review-links``.

    Args:
        query: Search query string.
        config: Loom configuration.
        project: Optional project name to filter by.
        limit: Maximum results to return.
        top_k: Number of vector candidates to fetch.
        context_note: Vault-relative path of the note the user is currently
            working in.  Used as the source for on-search link queuing.
            Pass None to disable on-search queuing for this call.

    Returns:
        Ranked list of HybridResult objects.
    """
    embedder = OllamaEmbedder(
        base_url=config.ollama_base_url,
        model=config.embedding_model,
    )

    try:
        embedding = await embedder.embed(query)
    except OllamaNotAvailableError:
        return []
    finally:
        await embedder.close()

    store = ChromaStore(persist_path=config.chroma_path)

    filter_dict = {"project": project} if project else None
    vector_hits = await store.query(embedding, top_k=top_k, filter=filter_dict)

    results: dict[str, HybridResult] = {}
    for hit in vector_hits:
        results[hit.path] = HybridResult(
            path=hit.path,
            score=hit.score,
            vector_score=hit.score,
            graph_hops=0,
            excerpt=hit.excerpt,
            metadata=hit.metadata,
        )

    db = get_connection()
    try:
        # Stage 2: Graph expansion
        graph = VaultGraph(db)
        seed_paths = [hit.path for hit in vector_hits if hit.path]
        if seed_paths:
            graph_nodes = graph.bfs(seed_paths, max_depth=2)

            async with VaultClient(config) as client:
                for node in graph_nodes:
                    if node.path not in results:
                        try:
                            content = await client.read_note(node.path)
                            excerpt = content[:500]
                        except (FileNotFoundError, Exception):
                            excerpt = ""

                        results[node.path] = HybridResult(
                            path=node.path,
                            score=0.0,
                            vector_score=0.0,
                            graph_hops=node.hops,
                            excerpt=excerpt,
                        )

        # Stage 3: Rerank
        for r in results.values():
            r.score = _combined_score(r.vector_score, r.graph_hops)

        ranked = sorted(results.values(), key=lambda r: r.score, reverse=True)
        ranked = ranked[:limit]

        # On-search link queuing (config-gated, requires a context note)
        if (
            config.semantic_links_enabled
            and config.semantic_links_auto_on_search
            and context_note
            and ranked
        ):
            result_paths = [r.path for r in ranked]
            result_scores = [r.vector_score for r in ranked]
            import contextlib  # noqa: PLC0415
            with contextlib.suppress(Exception):
                queue_search_links(
                    db,
                    source_path=context_note,
                    result_paths=result_paths,
                    similarities=result_scores,
                    threshold=config.semantic_links_threshold,
                )

    finally:
        db.close()

    return ranked


def _combined_score(vector_score: float, graph_hops: int) -> float:
    """Compute combined relevance score.

    Score = 0.6 * vector_score + 0.4 * (1 / graph_hops)
    If graph_hops is 0 (direct vector hit), graph component is 0.
    """
    vector_component = vector_score * 0.6
    graph_component = (1.0 / graph_hops) * 0.4 if graph_hops > 0 else 0.0
    return vector_component + graph_component
