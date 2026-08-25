"""Interface rendering for ALLAN.

The engine does not format anything for humans. It emits structured progress
events (plain dicts) and one final reply string; this module decides what a
given interface actually shows.

That split is the point. A terminal wants "step 3: memory:search -> ok". A voice
interface must never say "task-1" out loud -- for speech, most events are simply
not worth uttering, and the few that are get said like a person would.

Event schema (see allanprime):
  {"type": "plan_set",     "tasks": [str], "count": int}
  {"type": "step_started", "step": int, "budget": int, "remaining": int,
                           "objective": str|None}
  {"type": "action",       "kind": str, "label": str, "ok": bool, "detail": str}
  {"type": "task_done",    "id": str, "title": str, "remaining": int}
  {"type": "rejected",     "reason": str, "detail": str}
  {"type": "needs_input",  "question": str}
  {"type": "wrapping_up",  "reason": str}
  {"type": "run_finished", "steps": int, "outcome": str, "reason": str|None}

Adding an interface means adding a style function and a registry entry. No
engine changes.
"""

import re

# Which style each interface uses when settings do not say otherwise.
DEFAULT_STYLE_BY_INTERFACE = {
    "terminal": "verbose",
    "voice": "spoken",
}
FALLBACK_STYLE = "verbose"

# Internal vocabulary that must never reach a spoken interface.
# Matches "task-1", "task 1" and "task1" -- ALLAN writes all three.
TASK_ID_PATTERN = re.compile(r"\btask[\s_-]?\d+\b", re.IGNORECASE)
STEP_NUMBER_PATTERN = re.compile(r"\bstep\s*\d+\b", re.IGNORECASE)

# Task opcodes whose effect is already reported by a dedicated event, so the raw
# action line would just be a duplicate.
REDUNDANT_TASK_ACTIONS = ("task:set", "task:done")


def resolve_style(interface_name, interface_rules=None):
    """Pick a progress style: explicit setting, then per-interface default."""
    name = str(interface_name or "").lower()
    rules = (interface_rules or {}).get(name) or {}
    progress = rules.get("progress")
    if isinstance(progress, dict) and progress.get("style"):
        return str(progress["style"]).lower()
    if isinstance(progress, str):
        return progress.lower()
    return DEFAULT_STYLE_BY_INTERFACE.get(name, FALLBACK_STYLE)


# --------------------------------------------------------------------------
# Styles. Each takes an event and returns a line to emit, or None for silence.
# --------------------------------------------------------------------------

def _verbose(event):
    """Full mechanical detail. Good for a terminal, useless for anything spoken."""
    kind = event.get("type")

    if kind == "plan_set":
        lines = [f"  plan: {event['count']} task(s)"]
        lines += [f"    {i}. {t}" for i, t in enumerate(event.get("tasks", []), 1)]
        return "\n".join(lines)

    if kind == "action":
        label = str(event.get("label") or "")
        # A successful task:set / task:done is already reported as plan_set /
        # task_done with the human-readable title; don't print it twice.
        if event.get("ok") and label.startswith(REDUNDANT_TASK_ACTIONS):
            return None
        status = "ok" if event.get("ok") else "FAILED"
        return f"  step {event.get('step')}: {label} -> {status}"

    if kind == "task_done":
        remaining = event.get("remaining", 0)
        tail = f" ({remaining} left)" if remaining else " (all done)"
        return f"  step {event.get('step')}: done - {event.get('title')}{tail}"

    if kind == "rejected":
        return f"  step {event.get('step')}: {event.get('detail')}"

    if kind == "needs_input":
        return f"  step {event.get('step')}: needs input from you"

    if kind == "wrapping_up":
        return f"  wrapping up: {event.get('reason')}"

    if kind == "run_finished" and event.get("outcome") != "complete":
        return f"  stopped after {event.get('steps')} step(s)"

    return None


def _spoken(event):
    """What a person would actually say while working. No ids, no step numbers.

    Almost everything is silence. A voice interface talking through its own
    bookkeeping is unbearable; it should work quietly and then answer.
    """
    kind = event.get("type")

    if kind == "plan_set" and event.get("count", 0) >= 3:
        return "Okay, this will take me a moment."

    if kind == "action" and not event.get("ok"):
        # Worth a word only because silence after a failure reads as a hang.
        return None

    if kind == "wrapping_up":
        return "Let me wrap up what I have."

    return None


def _minimal(event):
    """One short line per step. For narrow surfaces like a status bar."""
    kind = event.get("type")
    if kind == "step_started":
        objective = event.get("objective")
        return f"working: {objective}" if objective else "working"
    if kind == "needs_input":
        return "waiting for you"
    return None


def _silent(event):
    return None


STYLES = {
    "verbose": _verbose,
    "spoken": _spoken,
    "minimal": _minimal,
    "silent": _silent,
}


def render(event, interface_name="terminal", interface_rules=None):
    """Turn one progress event into interface-appropriate output, or None."""
    if not isinstance(event, dict):
        return None
    style = STYLES.get(resolve_style(interface_name, interface_rules), _verbose)
    try:
        return style(event)
    except Exception:
        return None


def make_progress_handler(interface_name="terminal", interface_rules=None, sink=print):
    """Build the on_progress callable to hand to ALLAN_prime.

    Swallows rendering errors: a cosmetic bug in an interface must never take
    down a run that is doing real work.
    """
    def handle(event):
        line = render(event, interface_name, interface_rules)
        if line:
            try:
                sink(line)
            except Exception:
                pass
    return handle


# --------------------------------------------------------------------------
# Final reply
# --------------------------------------------------------------------------

def sanitize_reply(text, interface_name="terminal"):
    """Last-resort scrub of internal vocabulary from a user-facing reply.

    The interface prompt already tells ALLAN not to say "task-1" out loud, but a
    prompt rule is a request, not a guarantee. For spoken interfaces we rewrite
    the few tokens that are unambiguously machine vocabulary. Everything else is
    left exactly as written -- this is a safety net, not a rewriter.
    """
    if not text:
        return text
    if resolve_style(interface_name) not in ("spoken", "minimal"):
        return text
    cleaned = TASK_ID_PATTERN.sub("that step", str(text))
    cleaned = STEP_NUMBER_PATTERN.sub("that step", cleaned)
    # "that step and that step" reads worse than the original; collapse repeats.
    cleaned = re.sub(r"(that step)(\s*(?:,|and|,\s*and)\s*that step)+", r"\1",
                     cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", cleaned).strip()
