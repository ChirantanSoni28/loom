"""Ollama embedding API client — hard dependency for vector indexing."""

import httpx


class OllamaNotAvailableError(Exception):
    """Raised when Ollama is not reachable."""

    def __init__(self, base_url: str) -> None:
        super().__init__(
            f"Ollama is not available at {base_url}\n"
            "Ensure Ollama is running: https://ollama.com/download\n"
            "Start it with: ollama serve"
        )


class OllamaEmbedder:
    """Async client for generating embeddings via Ollama's /api/embed endpoint.

    Args:
        base_url: Ollama base URL (default: http://localhost:11434).
        model: Embedding model name (default: nomic-embed-text).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=120.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as a list of floats.

        Raises:
            OllamaNotAvailableError: If Ollama is unreachable.
        """
        client = await self._get_client()
        try:
            response = await client.post(
                "/api/embed",
                json={"model": self.model, "input": text},
            )
            response.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise OllamaNotAvailableError(self.base_url)

        data = response.json()
        embeddings = data.get("embeddings", [])
        if not embeddings:
            raise ValueError(f"No embeddings returned for model '{self.model}'")
        return embeddings[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Uses Ollama's batch input support. Falls back to sequential
        embedding if batch fails.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors, one per input text.

        Raises:
            OllamaNotAvailableError: If Ollama is unreachable.
        """
        if not texts:
            return []

        client = await self._get_client()
        try:
            response = await client.post(
                "/api/embed",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise OllamaNotAvailableError(self.base_url)

        data = response.json()
        embeddings = data.get("embeddings", [])

        if len(embeddings) == len(texts):
            return embeddings

        # Fallback: embed one at a time
        results: list[list[float]] = []
        for text in texts:
            vec = await self.embed(text)
            results.append(vec)
        return results
