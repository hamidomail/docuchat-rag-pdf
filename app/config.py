"""Runtime configuration, read from environment variables (or a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader so the project has no extra dependency for it."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    # LLM
    llm_provider: str          # openai | anthropic | none
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    anthropic_api_key: str
    anthropic_model: str
    temperature: float
    # Embeddings (dense retrieval). "none" = BM25 keyword retrieval only.
    embeddings_provider: str   # none | openai | sentence-transformers
    embeddings_model: str
    # Retrieval
    chunk_size: int
    chunk_overlap: int
    top_k: int
    max_upload_mb: int

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        provider = _env("LLM_PROVIDER", "auto").lower()
        if provider == "auto":
            if _env("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif _env("OPENAI_API_KEY") or _env("OPENAI_BASE_URL"):
                provider = "openai"
            else:
                provider = "none"

        emb_provider = _env("EMBEDDINGS_PROVIDER", "none").lower()
        default_emb_model = {
            "openai": "text-embedding-3-small",
            "sentence-transformers": "sentence-transformers/all-MiniLM-L6-v2",
        }.get(emb_provider, "")

        return cls(
            data_dir=Path(_env("DATA_DIR", "data")),
            llm_provider=provider,
            openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_model=_env("OPENAI_MODEL", "gpt-4.1-mini"),
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            anthropic_model=_env("ANTHROPIC_MODEL", "claude-haiku-5-5"),
            temperature=float(_env("LLM_TEMPERATURE", "0.1")),
            embeddings_provider=emb_provider,
            embeddings_model=_env("EMBEDDINGS_MODEL", default_emb_model),
            chunk_size=int(_env("CHUNK_SIZE", "900")),
            chunk_overlap=int(_env("CHUNK_OVERLAP", "150")),
            top_k=int(_env("TOP_K", "5")),
            max_upload_mb=int(_env("MAX_UPLOAD_MB", "25")),
        )

    @property
    def model_label(self) -> str:
        if self.llm_provider == "openai":
            return self.openai_model
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        return "demo mode (no LLM)"
