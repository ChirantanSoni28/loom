"""Retrieval engine — embeddings, chunking, vector indexing, and search."""

from loom.retrieval.chunker import Chunk, chunk_note
from loom.retrieval.embedder import OllamaEmbedder, OllamaNotAvailableError
from loom.retrieval.indexer import IndexReport, index_note, reindex_vault
from loom.retrieval.pinecone_store import PineconeStore, SearchResult

__all__ = [
    "Chunk",
    "IndexReport",
    "OllamaEmbedder",
    "OllamaNotAvailableError",
    "PineconeStore",
    "SearchResult",
    "chunk_note",
    "index_note",
    "reindex_vault",
]
