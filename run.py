"""
run.py — start ALLAN and talk to Allan Prime in your terminal.

Run it from the v2 folder:

    cd v2
    python run.py

Fastest way to see it work, with zero setup (no API key, no Ollama):

    Windows (PowerShell):   $env:ALLAN_BACKEND="echo"; python run.py
    Windows (cmd):          set ALLAN_BACKEND=echo && python run.py
    macOS / Linux:          ALLAN_BACKEND=echo python run.py

To use Claude as AP's real brain, set your key first:

    Windows (PowerShell):   $env:ANTHROPIC_API_KEY="sk-ant-..."; python run.py
    macOS / Linux:          export ANTHROPIC_API_KEY=sk-ant-...  && python run.py

Type 'exit' or 'quit' (or press Ctrl-C) to stop. Everything you and AP say is
written to the ledger at allan_data/log.jsonl.
"""
from __future__ import annotations

from allan.config import Config
from allan.log import Log
from allan.ap import AllanPrime


def main() -> None:
    config = Config.from_env()
    log = Log(config.log_path)
    log.record("session_start", {"backend": config.backend, "model": config.model})

    ap = AllanPrime(config, log)

    print("ALLAN v0 — Allan Prime")
    print(f"  backend: {config.backend}    model: {config.model}")
    print(f"  ledger:  {config.log_path}")
    print("  (type 'exit' to quit)\n")

    try:
        while True:
            try:
                user_text = input("you > ").strip()
            except EOFError:
                break  # end of piped input
            if not user_text:
                continue
            if user_text.lower() in ("exit", "quit"):
                break
            try:
                reply = ap.send(user_text)
            except Exception as e:
                # Don't crash the whole session on one bad call; report and continue.
                print(f"\n[error] {e}\n")
                continue
            print(f"\nAP  > {reply}\n")
    except KeyboardInterrupt:
        print()
    finally:
        log.record("session_end", {})
        log.close()
        print("...logged. Goodbye.")


if __name__ == "__main__":
    main()
