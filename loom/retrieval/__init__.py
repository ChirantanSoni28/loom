"""Retrieval engine — embeddings, chunking, vector indexing, and search."""

from loom.retrieval.chroma_store import ChromaStore, SearchResult
from loom.retrieval.chunker import Chunk, chunk_note
from loom.retrieval.embedder import OllamaEmbedder, OllamaNotAvailableError
from loom.retrieval.indexer import IndexReport, index_note, reindex_vault

__all__ = [
    "ChromaStore",
    "Chunk",
    "IndexReport",
    "OllamaEmbedder",
    "OllamaNotAvailableError",
    "SearchResult",
    "chunk_note",
    "index_note",
    "reindex_vault",
]
