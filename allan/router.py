"""
router.py — the brain abstraction, and the model router.

An allan does not know or care whether its "brain" is a local model or a paid
API. It just calls Router.complete(...). The router picks the backend and —
this is the important part — records every request and every response to the
ledger. So every thought ALLAN has is on the record.

Backends:
  * anthropic — Claude, via the official SDK. AP's real brain. Needs
                ANTHROPIC_API_KEY in the environment.
  * ollama    — a local model served by Ollama on your PC. Free and private.
  * echo      — no model at all; it just echoes your words back. Needs nothing,
                so you can run the whole skeleton with zero setup to watch the
                loop and the ledger work.

The anthropic and ollama libraries are imported lazily (only when that backend
is actually used), so 'echo' runs on a bare Python install with nothing extra.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .config import Config
from .log import Log


class Router:
    def __init__(self, config: Config, log: Log):
        self.config = config
        self.log = log

    def complete(
        self,
        system: str,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
    ) -> str:
        """Send a conversation to a model and return its reply text.

        `system`   — the standing instructions (who the agent is).
        `messages` — the conversation so far, as a list of
                     {"role": "user"|"assistant", "content": "..."}.
        """
        model = model or self.config.model
        backend = self.config.backend

        # Record the request BEFORE calling out, so even a crash mid-call
        # leaves a trace of what we were trying to do.
        self.log.record(
            "model_request",
            {"backend": backend, "model": model, "system": system, "messages": messages},
        )

        try:
            if backend == "anthropic":
                text = self._anthropic(system, messages, model)
            elif backend == "ollama":
                text = self._ollama(system, messages, model)
            elif backend == "echo":
                text = self._echo(messages)
            else:
                raise ValueError(
                    f"Unknown backend '{backend}'. Use anthropic, ollama, or echo."
                )
        except Exception as e:
            # Errors are part of the honest record too.
            self.log.record(
                "model_error", {"backend": backend, "model": model, "error": repr(e)}
            )
            raise

        self.log.record("model_response", {"backend": backend, "model": model, "text": text})
        return text

    # --- backends -----------------------------------------------------------

    def _anthropic(self, system: str, messages: List[Dict[str, str]], model: str) -> str:
        import anthropic  # lazy import: only needed for this backend

        if not self.config.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it, or run with "
                "ALLAN_BACKEND=echo to test offline."
            )
        client = anthropic.Anthropic(api_key=self.config.anthropic_api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=self.config.max_tokens,
            system=system,
            messages=messages,
        )
        # A reply can contain several blocks; keep the text ones and join them.
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )

    def _ollama(self, system: str, messages: List[Dict[str, str]], model: str) -> str:
        import ollama  # lazy import: only needed for this backend

        client = ollama.Client(host=self.config.ollama_host) if self.config.ollama_host else ollama
        # Ollama takes the system prompt as the first message in the list.
        full = ([{"role": "system", "content": system}] if system else []) + messages
        resp = client.chat(model=model, messages=full)
        return resp["message"]["content"]

    def _echo(self, messages: List[Dict[str, str]]) -> str:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        return f"(echo) You said: {last_user}"
