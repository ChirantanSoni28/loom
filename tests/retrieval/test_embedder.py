"""Tests for loom.retrieval.embedder — Ollama embedding client."""

import pytest

from loom.retrieval.embedder import OllamaEmbedder, OllamaNotAvailableError


class TestOllamaNotAvailableError:
    """Test the error message includes helpful instructions."""

    def test_error_message_includes_url(self) -> None:
        err = OllamaNotAvailableError("http://localhost:11434")
        assert "http://localhost:11434" in str(err)

    def test_error_message_includes_install_link(self) -> None:
        err = OllamaNotAvailableError("http://localhost:11434")
        assert "ollama.com" in str(err)

    def test_error_message_includes_serve_hint(self) -> None:
        err = OllamaNotAvailableError("http://localhost:11434")
        assert "ollama serve" in str(err)


class TestOllamaEmbedder:
    """Test OllamaEmbedder initialization and error handling."""

    def test_default_config(self) -> None:
        embedder = OllamaEmbedder()
        assert embedder.base_url == "http://localhost:11434"
        assert embedder.model == "nomic-embed-text"

    def test_custom_config(self) -> None:
        embedder = OllamaEmbedder(
            base_url="http://custom:1234",
            model="custom-model",
        )
        assert embedder.base_url == "http://custom:1234"
        assert embedder.model == "custom-model"

    def test_trailing_slash_stripped(self) -> None:
        embedder = OllamaEmbedder(base_url="http://localhost:11434/")
        assert embedder.base_url == "http://localhost:11434"

    @pytest.mark.asyncio
    async def test_embed_raises_when_ollama_unreachable(self) -> None:
        embedder = OllamaEmbedder(base_url="http://localhost:99999")
        with pytest.raises(OllamaNotAvailableError):
            await embedder.embed("test")
        await embedder.close()

    @pytest.mark.asyncio
    async def test_embed_batch_empty_returns_empty(self) -> None:
        embedder = OllamaEmbedder()
        result = await embedder.embed_batch([])
        assert result == []
        await embedder.close()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        embedder = OllamaEmbedder()
        await embedder.close()
        await embedder.close()  # Should not raise
