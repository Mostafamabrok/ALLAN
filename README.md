# ALLAN

*Autonomous Language Learning Agent Network* — a personal assistant that runs
on your own PC and does real work for you. See `ARCHITECTURE.md` for the full
design and the reasoning behind it.

This is the ground-up rebuild. The original prototype has been retired into
`_to_delete/` (safe to delete once you're happy).

## Where things are

| Path | What it is |
|------|------------|
| `ARCHITECTURE.md` | The blueprint: vision, principles, and every component. |
| `allan/config.py` | Every setting, read from environment variables. |
| `allan/log.py`    | The **ledger** — an append-only record of everything. The single source of truth. |
| `allan/router.py` | The **brain abstraction** — one call that talks to Claude, a local model, or a plain echo, and logs every request and reply. |
| `allan/ap.py`     | **Allan Prime** — the one agent you talk to. |
| `run.py`          | The terminal chat you actually run. |
| `_to_delete/`     | The old v1 prototype, retired. Delete when ready. |

## Current stage: v0 (the skeleton)

One agent you can talk to (Allan Prime), on top of an append-only ledger that
records everything. No tools, no memory, no helper agents yet — those come in
later versions (see `ARCHITECTURE.md`, section 10). The point of v0 is that
it's real and completely legible.

### How to run it

From the repo root:

```
python run.py
```

**Zero-setup demo** (no API key, no Ollama — just watch the loop and ledger work):

```
# Windows PowerShell
$env:ALLAN_BACKEND="echo"; python run.py

# Windows cmd
set ALLAN_BACKEND=echo && python run.py

# macOS / Linux
ALLAN_BACKEND=echo python run.py
```

**With Claude** (AP's real brain):

```
pip install -r requirements.txt
# PowerShell:  $env:ANTHROPIC_API_KEY="sk-ant-..."; python run.py
# bash:        export ANTHROPIC_API_KEY=sk-ant-... && python run.py
```

**With a local model** (needs Ollama running and a model pulled):

```
pip install -r requirements.txt
# PowerShell:  $env:ALLAN_BACKEND="ollama"; $env:ALLAN_MODEL="gemma3"; python run.py
```

### The ledger

Everything is written to `allan_data/log.jsonl`, one JSON object per line.
Open it in any text editor to read ALLAN's whole history. Keep it out of git:
add `allan_data/` to your `.gitignore`.

### Settings (environment variables)

| Variable | Default | Meaning |
|----------|---------|---------|
| `ALLAN_BACKEND` | `anthropic` | `anthropic`, `ollama`, or `echo` |
| `ALLAN_MODEL` | per-backend | e.g. `claude-sonnet-5`, `claude-opus-5`, `gemma3` |
| `ALLAN_LOG_PATH` | `allan_data/log.jsonl` | where the ledger is written |
| `ALLAN_MAX_TOKENS` | `2048` | max reply length |
| `ANTHROPIC_API_KEY` | — | your Claude key (anthropic backend only) |
| `OLLAMA_HOST` | — | custom Ollama URL (ollama backend only) |

## What's next: v1

Give AP hands — a browser it drives using your already-signed-in session — so
it can read ManageBac and tell you what's due. See `ARCHITECTURE.md`, section 10.
