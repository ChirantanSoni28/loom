"""Tests for loom.config — config loading, saving, masking, and validation."""

import json
import stat
from pathlib import Path

import pytest

from loom.config import (
    LoomConfig,
    LoomConfigNotFoundError,
    _mask_value,
    load_config,
    save_config,
    set_config_value,
)


@pytest.fixture()
def loom_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect LOOM_DIR and CONFIG_PATH to a temp directory."""
    import loom.config as cfg

    config_path = tmp_path / "loom-settings.json"
    monkeypatch.setattr(cfg, "LOOM_DIR", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_path)
    return tmp_path


class TestLoomConfig:
    def test_defaults(self) -> None:
        config = LoomConfig()
        assert config.embedding_model == "nomic-embed-text"
        assert config.obsidian_vault_name == ""
        assert config.compression_enabled is False
        assert config.compression_require_approval is True

    def test_round_trip_settings_dict(self) -> None:
        config = LoomConfig(
            obsidian_vault_name="my-vault",
            compression_anthropic_key="anthro-key-1234",
        )
        settings = config.to_settings_dict()
        restored = LoomConfig.from_settings_dict(settings)
        assert restored.obsidian_vault_name == "my-vault"
        assert restored.compression_anthropic_key == "anthro-key-1234"
        assert restored.vault_path == config.vault_path

    def test_masked_display_hides_secrets(self) -> None:
        config = LoomConfig(
            compression_anthropic_key="anthro-key-1234",
        )
        masked = config.masked_display()
        assert masked["compression"]["anthropic_api_key"] == "...1234"

    def test_vault_name_not_masked(self) -> None:
        config = LoomConfig(obsidian_vault_name="my-vault")
        masked = config.masked_display()
        assert masked["obsidian"]["vault_name"] == "my-vault"

    def test_chroma_path_in_settings(self) -> None:
        config = LoomConfig()
        settings = config.to_settings_dict()
        assert "chroma_path" in settings


class TestMaskValue:
    def test_empty(self) -> None:
        assert _mask_value("") == "(not set)"

    def test_short(self) -> None:
        assert _mask_value("abc") == "****"

    def test_normal(self) -> None:
        assert _mask_value("my-secret-key") == "...-key"


class TestSaveLoadConfig:
    def test_save_and_load(self, loom_dir: Path) -> None:
        config = LoomConfig(obsidian_vault_name="test-vault")
        save_config(config)

        loaded = load_config()
        assert loaded.obsidian_vault_name == "test-vault"

    def test_save_sets_permissions_600(self, loom_dir: Path) -> None:
        save_config(LoomConfig())
        config_path = loom_dir / "loom-settings.json"
        mode = config_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_load_missing_raises(self, loom_dir: Path) -> None:
        with pytest.raises(LoomConfigNotFoundError, match="loom setup"):
            load_config()

    def test_save_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import loom.config as cfg

        nested = tmp_path / "deep" / "nested"
        monkeypatch.setattr(cfg, "LOOM_DIR", nested)
        monkeypatch.setattr(cfg, "CONFIG_PATH", nested / "loom-settings.json")

        save_config(LoomConfig())
        assert (nested / "loom-settings.json").exists()


class TestSetConfigValue:
    def test_set_string_key(self, loom_dir: Path) -> None:
        save_config(LoomConfig())
        updated = set_config_value("embedding_model", "all-minilm")
        assert updated.embedding_model == "all-minilm"

        # Verify persisted
        loaded = load_config()
        assert loaded.embedding_model == "all-minilm"

    def test_set_bool_key(self, loom_dir: Path) -> None:
        save_config(LoomConfig())
        updated = set_config_value("compression_enabled", "true")
        assert updated.compression_enabled is True

    def test_set_int_key(self, loom_dir: Path) -> None:
        save_config(LoomConfig())
        updated = set_config_value("embedding_dimensions", "512")
        assert updated.embedding_dimensions == 512

    def test_set_unknown_key_raises(self, loom_dir: Path) -> None:
        save_config(LoomConfig())
        with pytest.raises(KeyError, match="Unknown config key"):
            set_config_value("nonexistent_key", "value")
