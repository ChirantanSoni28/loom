"""Pinecone vector store — upsert, query, and delete operations."""

from dataclasses import dataclass

from pinecone import Pinecone

from loom.retrieval.chunker import Chunk

# Pinecone recommends batch sizes of 100
_UPSERT_BATCH_SIZE = 100


@dataclass
class SearchResult:
    """A search result from Pinecone vector query."""

    path: str
    score: float
    excerpt: str
    metadata: dict


class PineconeStore:
    """Async-style wrapper around the Pinecone index.

    Args:
        api_key: Pinecone API key.
        index_name: Name of the Pinecone index.
        dimensions: Embedding vector dimensions (default: 768).
    """

    def __init__(
        self,
        api_key: str,
        index_name: str,
        dimensions: int = 768,
    ) -> None:
        self._pc = Pinecone(api_key=api_key)
        self._index = self._pc.Index(index_name)
        self._dimensions = dimensions

    async def upsert_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> int:
        """Upsert chunk vectors with metadata into Pinecone.

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

        vectors = [
            {
                "id": chunk.chunk_id,
                "values": embedding,
                "metadata": {
                    **chunk.metadata,
                    "text": chunk.text[:1000],  # Store truncated text for excerpts
                },
            }
            for chunk, embedding in zip(chunks, embeddings)
        ]

        total = 0
        for i in range(0, len(vectors), _UPSERT_BATCH_SIZE):
            batch = vectors[i : i + _UPSERT_BATCH_SIZE]
            self._index.upsert(vectors=batch)
            total += len(batch)

        return total

    async def query(
        self,
        embedding: list[float],
        top_k: int = 10,
        filter: dict | None = None,
    ) -> list[SearchResult]:
        """Query Pinecone for nearest neighbors.

        Args:
            embedding: Query embedding vector.
            top_k: Number of results to return.
            filter: Optional metadata filter (e.g. {"project": "my-repo"}).

        Returns:
            Ranked list of SearchResult objects.
        """
        query_params: dict = {
            "vector": embedding,
            "top_k": top_k,
            "include_metadata": True,
        }
        if filter:
            query_params["filter"] = filter

        response = self._index.query(**query_params)

        results: list[SearchResult] = []
        for match in response.get("matches", []):
            metadata = match.get("metadata", {})
            results.append(
                SearchResult(
                    path=metadata.get("note_path", ""),
                    score=match.get("score", 0.0),
                    excerpt=metadata.get("text", ""),
                    metadata={k: v for k, v in metadata.items() if k != "text"},
                )
            )

        return results

    async def delete_by_path(self, note_path: str) -> None:
        """Remove all vectors belonging to a note.

        Uses metadata filter to find and delete all chunks of a note.

        Args:
            note_path: Vault-relative path of the note to remove.
        """
        # Pinecone delete with metadata filter
        self._index.delete(filter={"note_path": {"$eq": note_path}})

    async def delete_ids(self, ids: list[str]) -> None:
        """Delete vectors by their IDs.

        Args:
            ids: List of vector IDs to delete.
        """
        if not ids:
            return
        for i in range(0, len(ids), _UPSERT_BATCH_SIZE):
            batch = ids[i : i + _UPSERT_BATCH_SIZE]
            self._index.delete(ids=batch)
