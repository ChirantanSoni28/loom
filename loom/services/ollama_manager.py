"""Ollama lifecycle manager — auto-install, auto-start, auto-pull."""

import platform
import shutil
import subprocess
import time

import httpx


class OllamaSetupError(Exception):
    """Raised when Ollama cannot be installed or started."""


class OllamaManager:
    """Manages the full Ollama lifecycle: install, start, and model pull.

    Designed to be called during `loom setup` for initial provisioning
    and at runtime for auto-recovery when Ollama is not responding.

    Args:
        base_url: Ollama server URL (default: http://localhost:11434).
        model: Embedding model to ensure is available.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def is_installed(self) -> bool:
        """Check if the ollama binary is on PATH."""
        return shutil.which("ollama") is not None

    def is_running(self) -> bool:
        """Check if the Ollama server is responding."""
        try:
            resp = httpx.get(f"{self.base_url}/", timeout=3.0)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            return False

    def has_model(self) -> bool:
        """Check if the configured embedding model is already pulled."""
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        return self.model in result.stdout

    def install(self) -> None:
        """Install Ollama for the current platform.

        macOS: uses Homebrew if available, otherwise raises with instructions.
        Linux: uses the official install script.

        Raises:
            OllamaSetupError: If installation fails.
        """
        system = platform.system().lower()

        if system == "darwin":
            self._install_macos()
        elif system == "linux":
            self._install_linux()
        else:
            raise OllamaSetupError(
                f"Automatic Ollama installation not supported on {system}. "
                "Install manually from https://ollama.com/download"
            )

    def _install_macos(self) -> None:
        """Install Ollama on macOS via Homebrew."""
        if not shutil.which("brew"):
            raise OllamaSetupError(
                "Homebrew not found. Install Ollama manually:\n"
                "  1. Install from https://ollama.com/download\n"
                "  2. Or install Homebrew first: https://brew.sh"
            )

        result = subprocess.run(
            ["brew", "install", "--quiet", "ollama"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise OllamaSetupError(
                f"Failed to install Ollama via Homebrew: {result.stderr.strip()}"
            )

    def _install_linux(self) -> None:
        """Install Ollama on Linux via official install script."""
        result = subprocess.run(
            ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise OllamaSetupError(
                f"Failed to install Ollama: {result.stderr.strip()}"
            )

    def start(self, timeout: float = 15.0) -> None:
        """Start the Ollama server in the background and wait until healthy.

        Args:
            timeout: Seconds to wait for the server to become healthy.

        Raises:
            OllamaSetupError: If the server doesn't start within the timeout.
        """
        if self.is_running():
            return

        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_running():
                return
            time.sleep(0.5)

        raise OllamaSetupError(
            f"Ollama server did not start within {timeout}s. "
            "Try starting manually: ollama serve"
        )

    def pull_model(self) -> None:
        """Pull the embedding model if not already present.

        Raises:
            OllamaSetupError: If the model pull fails.
        """
        if self.has_model():
            return

        result = subprocess.run(
            ["ollama", "pull", self.model],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise OllamaSetupError(
                f"Failed to pull model '{self.model}': {result.stderr.strip()}"
            )

    def ensure_ready(self) -> None:
        """Full lifecycle: install if missing, start if stopped, pull model.

        This is the main entry point for both setup and runtime recovery.

        Raises:
            OllamaSetupError: If any step fails.
        """
        if not self.is_installed():
            self.install()

        if not self.is_running():
            self.start()

        self.pull_model()

    def ensure_running(self) -> None:
        """Lighter check: start server if not running (assumes installed).

        Used at runtime by the embedder for auto-recovery.

        Raises:
            OllamaSetupError: If the server cannot be started.
        """
        if not self.is_running():
            self.start()

    def get_version(self) -> str:
        """Return the Ollama version string."""
        result = subprocess.run(
            ["ollama", "version"],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
