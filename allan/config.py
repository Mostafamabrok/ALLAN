"""
config.py — every setting ALLAN has, in one place.

All configuration is read from environment variables, so you never edit code
to change a model or a file path. Sensible defaults mean it also runs with
almost zero setup. The 'echo' backend in particular needs nothing at all.

Environment variables you can set:
  ALLAN_BACKEND     "anthropic" (default) | "ollama" | "echo"
  ALLAN_MODEL       model id; defaults to a sensible one per backend
  ALLAN_LOG_PATH    where the ledger is written (default: allan_data/log.jsonl)
  ALLAN_MAX_TOKENS  max length of a reply (default: 2048)
  ANTHROPIC_API_KEY your Claude API key (needed only for the anthropic backend)
  OLLAMA_HOST       custom Ollama server URL (optional; needed only for ollama)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The default model for each backend.
#   - anthropic: Claude Sonnet 5 is the best balance of speed and intelligence.
#     For heavier reasoning later, set ALLAN_MODEL=claude-opus-5.
#   - ollama: a local model served on your PC (change to whatever you've pulled).
#   - echo: no model at all; it just echoes. Used for offline testing.
_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "ollama": "gemma3",
    "echo": "echo",
}


@dataclass
class Config:
    backend: str
    model: str
    log_path: Path
    anthropic_api_key: Optional[str]
    ollama_host: Optional[str]
    max_tokens: int

    @classmethod
    def from_env(cls) -> "Config":
        backend = os.environ.get("ALLAN_BACKEND", "anthropic").strip().lower()
        model = os.environ.get("ALLAN_MODEL", _DEFAULT_MODELS.get(backend, "echo"))
        log_path = Path(os.environ.get("ALLAN_LOG_PATH", "allan_data/log.jsonl"))
        return cls(
            backend=backend,
            model=model,
            log_path=log_path,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            ollama_host=os.environ.get("OLLAMA_HOST"),
            max_tokens=int(os.environ.get("ALLAN_MAX_TOKENS", "2048")),
        )
