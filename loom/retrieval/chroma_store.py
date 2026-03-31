"""ChromaDB vector store — local-first upsert, query, and delete operations."""

from dataclasses import dataclass
from pathlib import Path

import chromadb

from loom.retrieval.chunker import Chunk

_COLLECTION_NAME = "loom-vault"


@dataclass
class SearchResult:
    """A search result from a vector query."""

    path: str
    score: float
    excerpt: str
    metadata: dict


class ChromaStore:
    """Local vector store backed by ChromaDB PersistentClient.

    Data is stored on disk at the configured path (default ~/.loom/chroma).
    No external services, accounts, or API keys required.

    Args:
        persist_path: Directory for ChromaDB data files.
    """

    def __init__(self, persist_path: str | Path) -> None:
        self._client = chromadb.PersistentClient(path=str(persist_path))
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    async def upsert_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> int:
        """Upsert chunk vectors with metadata.

        Args:
            chunks: List of text chunks with metadata.
            embeddings: Corresponding embedding vectors.

        Returns:
            Number of vectors upserted.
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings"
            )

        if not chunks:
            return 0

        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.text[:1000] for chunk in chunks]
        metadatas = [
            {**chunk.metadata, "note_path": chunk.note_path}
            for chunk in chunks
        ]

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        return len(chunks)

    async def query(
        self,
        embedding: list[float],
        top_k: int = 10,
        filter: dict | None = None,
    ) -> list[SearchResult]:
        """Query for nearest neighbors.

        Args:
            embedding: Query embedding vector.
            top_k: Number of results to return.
            filter: Optional metadata filter (e.g. {"project": "my-repo"}).

        Returns:
            Ranked list of SearchResult objects.
        """
        query_params: dict = {
            "query_embeddings": [embedding],
            "n_results": top_k,
        }
        if filter:
            query_params["where"] = filter

        response = self._collection.query(**query_params)

        results: list[SearchResult] = []
        if not response["ids"] or not response["ids"][0]:
            return results

        ids = response["ids"][0]
        distances = response["distances"][0] if response["distances"] else [0.0] * len(ids)
        documents = response["documents"][0] if response["documents"] else [""] * len(ids)
        metadatas = response["metadatas"][0] if response["metadatas"] else [{}] * len(ids)

        for i, _id in enumerate(ids):
            meta = metadatas[i] or {}
            score = 1.0 - distances[i]
            results.append(
                SearchResult(
                    path=meta.get("note_path", ""),
                    score=score,
                    excerpt=documents[i] or "",
                    metadata={k: v for k, v in meta.items() if k != "note_path"},
                )
            )

        return results

    async def delete_by_path(self, note_path: str) -> None:
        """Remove all vectors belonging to a note.

        Args:
            note_path: Vault-relative path of the note to remove.
        """
        self._collection.delete(where={"note_path": note_path})

    async def delete_ids(self, ids: list[str]) -> None:
        """Delete vectors by their IDs.

        Args:
            ids: List of vector IDs to delete.
        """
        if not ids:
            return
        self._collection.delete(ids=ids)
