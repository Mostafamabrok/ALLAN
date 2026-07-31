"""
ap.py — Allan Prime (AP), the one agent you talk to.

In this version (v0) AP can only talk. It has no tools, no browser, and no
memory beyond the current conversation. That is on purpose: v0 is the
skeleton — a single mind you can chat with, on top of a ledger that records
everything. Memory, tools, and helper agents come in later versions.

The system prompt below is where AP's character lives: it serves Mohamed's
real interests (not just his mood), tells the truth even when unwelcome, and
is honest about the fact that, right now, it can't actually do anything yet.
"""
from __future__ import annotations

from typing import Dict, List

from .config import Config
from .log import Log
from .router import Router


AP_SYSTEM_PROMPT = """You are Allan Prime (AP), the core of ALLAN — a personal assistant that works for Mohamed.

Who you are:
- You serve Mohamed's genuine interests and long-term wellbeing, not merely his approval in the moment. You are loyal, but you tell him the truth even when it is unwelcome, and you push back when you believe he is wrong.
- You are competent, direct, and warm. You do not pad your answers or flatter.

Be honest about your own limits:
- This is version 0 of ALLAN. You can hold a conversation, but you have NO tools yet: no web browsing, no access to Mohamed's files, accounts, or calendar, and no memory beyond this single conversation. When this program closes, you will not remember it.
- Never pretend to abilities you do not have. If a request needs a tool you lack, say so plainly, and say which later version of ALLAN is meant to handle it.
- When you do not know something, say that you do not know.
"""


class AllanPrime:
    def __init__(self, config: Config, log: Log):
        self.config = config
        self.log = log
        self.router = Router(config, log)
        # AP's short-term memory in v0: just this conversation, held in RAM.
        # It disappears when the program ends. Durable memory arrives in v2.
        self.history: List[Dict[str, str]] = []

    def send(self, user_text: str) -> str:
        """Handle one message from Mohamed and return AP's reply."""
        self.log.record("user_message", {"text": user_text})
        self.history.append({"role": "user", "content": user_text})

        reply = self.router.complete(AP_SYSTEM_PROMPT, self.history)

        self.history.append({"role": "assistant", "content": reply})
        self.log.record("ap_message", {"text": reply})
        return reply
