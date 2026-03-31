"""Retrieval engine — embeddings, chunking, vector indexing, and search."""

from loom.retrieval.chroma_store import ChromaStore, SearchResult
from loom.retrieval.chunker import Chunk, chunk_note
from loom.retrieval.embedder import OllamaEmbedder, OllamaNotAvailableError
from loom.retrieval.indexer import IndexReport, index_note, reindex_vault
from loom.retrieval.semantic_links import (
    LinkCandidate,
    approve_link,
    discover_links,
    get_pending_links,
    queue_search_links,
    reject_link,
)

__all__ = [
    "Chunk",
    "ChromaStore",
    "IndexReport",
    "LinkCandidate",
    "OllamaEmbedder",
    "OllamaNotAvailableError",
    "SearchResult",
    "approve_link",
    "chunk_note",
    "discover_links",
    "get_pending_links",
    "index_note",
    "queue_search_links",
    "reindex_vault",
    "reject_link",
]
