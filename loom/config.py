"""Configuration loader for ~/.loom/loom-settings.json."""

import json
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

LOOM_DIR = Path.home() / ".loom"
CONFIG_PATH = LOOM_DIR / "loom-settings.json"

# Keys that contain secrets and should be masked in display
_SECRET_KEYS = {"pinecone_api_key", "compression_anthropic_key"}


class LoomConfigNotFoundError(Exception):
    """Raised when loom-settings.json does not exist."""

    def __init__(self) -> None:
        super().__init__(
            f"Loom configuration not found at {CONFIG_PATH}\n"
            "Run `loom setup` to create it."
        )


@dataclass
class LoomConfig:
    vault_path: Path = field(default_factory=lambda: LOOM_DIR / "vault")
    obsidian_vault_name: str = ""
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768
    ollama_base_url: str = "http://localhost:11434"
    pinecone_api_key: str = ""
    pinecone_index_name: str = "loom-vault"
    compression_enabled: bool = False
    compression_require_approval: bool = True
    compression_anthropic_key: str | None = None
    hot_ttl_days: int = 7
    warm_ttl_days: int = 30

    def to_settings_dict(self) -> dict:
        """Convert to the nested JSON structure used by loom-settings.json."""
        return {
            "vault_path": str(self.vault_path),
            "obsidian": {
                "vault_name": self.obsidian_vault_name,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "model": self.embedding_model,
                "dimensions": self.embedding_dimensions,
                "ollama_base_url": self.ollama_base_url,
            },
            "pinecone": {
                "api_key": self.pinecone_api_key,
                "index_name": self.pinecone_index_name,
            },
            "compression": {
                "enabled": self.compression_enabled,
                "require_user_approval": self.compression_require_approval,
                "anthropic_api_key": self.compression_anthropic_key or "",
                "hot_ttl_days": self.hot_ttl_days,
                "warm_ttl_days": self.warm_ttl_days,
            },
        }

    @classmethod
    def from_settings_dict(cls, data: dict) -> "LoomConfig":
        """Create a LoomConfig from the nested JSON structure."""
        obsidian = data.get("obsidian", {})
        embedding = data.get("embedding", {})
        pinecone = data.get("pinecone", {})
        compression = data.get("compression", {})

        return cls(
            vault_path=Path(data.get("vault_path", str(LOOM_DIR / "vault"))),
            obsidian_vault_name=obsidian.get("vault_name", ""),
            embedding_provider=embedding.get("provider", "ollama"),
            embedding_model=embedding.get("model", "nomic-embed-text"),
            embedding_dimensions=embedding.get("dimensions", 768),
            ollama_base_url=embedding.get("ollama_base_url", "http://localhost:11434"),
            pinecone_api_key=pinecone.get("api_key", ""),
            pinecone_index_name=pinecone.get("index_name", "loom-vault"),
            compression_enabled=compression.get("enabled", False),
            compression_require_approval=compression.get("require_user_approval", True),
            compression_anthropic_key=compression.get("anthropic_api_key") or None,
            hot_ttl_days=compression.get("hot_ttl_days", 7),
            warm_ttl_days=compression.get("warm_ttl_days", 30),
        )

    def masked_display(self) -> dict:
        """Return settings dict with secret values masked (last 4 chars visible)."""
        settings = self.to_settings_dict()
        _mask_secrets(settings)
        return settings


def _mask_value(value: str) -> str:
    """Mask a secret value, showing only the last 4 characters."""
    if not value:
        return "(not set)"
    if len(value) <= 4:
        return "****"
    return f"...{value[-4:]}"


def _mask_secrets(d: dict) -> None:
    """Recursively mask known secret keys in a nested dict."""
    secret_json_keys = {"api_key", "anthropic_api_key"}
    for key, value in d.items():
        if isinstance(value, dict):
            _mask_secrets(value)
        elif key in secret_json_keys and isinstance(value, str):
            d[key] = _mask_value(value)


def load_config() -> LoomConfig:
    """Load from ~/.loom/loom-settings.json.

    Raises LoomConfigNotFoundError with setup instructions if not found.
    """
    if not CONFIG_PATH.exists():
        raise LoomConfigNotFoundError()

    data = json.loads(CONFIG_PATH.read_text())
    return LoomConfig.from_settings_dict(data)


def save_config(config: LoomConfig) -> None:
    """Write to ~/.loom/loom-settings.json with secure permissions (600)."""
    LOOM_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config.to_settings_dict(), indent=2) + "\n")
    CONFIG_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)


def set_config_value(key: str, value: str) -> LoomConfig:
    """Update a single flat config key and save.

    Accepts flat keys like 'obsidian_api_key', 'embedding_model', etc.
    """
    config = load_config()
    flat = asdict(config)
    if key not in flat:
        raise KeyError(
            f"Unknown config key: {key!r}. "
            f"Valid keys: {', '.join(sorted(flat.keys()))}"
        )

    # Coerce types to match the dataclass field
    current = flat[key]
    if isinstance(current, bool):
        value = value.lower() in ("true", "1", "yes")  # type: ignore[assignment]
    elif isinstance(current, int):
        value = int(value)  # type: ignore[assignment]
    elif isinstance(current, Path):
        value = Path(value)  # type: ignore[assignment]

    setattr(config, key, value)
    save_config(config)
    return config
