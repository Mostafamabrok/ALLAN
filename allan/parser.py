"""Opcode parsing and routing for ALLAN.

Three opcodes, each a separate execution path:
  <tool>   -> tool_caller  (scripts in tool_library/)
  <memory> -> memory       (sticky / topical / summary / raw)
  <task>   -> tasks        (the loop's control state)

Blocks are executed in the order they appear in the response, and each one
reports its own success or failure. The loop needs that granularity: one failed
memory call should not discard a tool result that worked in the same step.
"""

import json
import re

from memory import call_memory
from tasks import call_task
from tool_caller import call_tool

BLOCK_PATTERN = re.compile(r"<(tool|memory|task)>(.*?)</\1>", re.DOTALL)

# Payloads that mean "memory" even when they arrive wrapped in the wrong tag.
MEMORY_ACTION_NAMES = {"search", "retrieve", "read", "write", "rewrite", "update", "delete", "find"}


# Characters that are harmless as trailing junk after a complete JSON object --
# an unbalanced closer the model tacked on, not a second intended action.
_HARMLESS_TRAILING = set("}] \t\r\n")


def has_actions(llm_response):
    return bool(BLOCK_PATTERN.search(llm_response or ""))


def _decode_payload(body, kind):
    """Parse an opcode body into a dict, tolerating a stray trailing brace.

    Models reliably emit one closing brace too many on nested payloads, e.g.
      {"action": "write", "args": {...}}}
    json.loads rejects the whole thing as "Extra data", so a perfectly good
    memory write silently never runs. raw_decode reads the first complete object
    and reports where it ended, letting us ignore junk that is only unbalanced
    closers. Anything else still fails loudly -- we will not guess at a payload
    that has real content we did not understand.
    """
    text = (body or "").strip()
    if not text:
        return None, f"Empty <{kind}> block."
    try:
        payload, end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON inside <{kind}> tags: {exc.msg}"

    if not isinstance(payload, dict):
        return None, f"<{kind}> payload must be a JSON object."

    trailing = text[end:]
    if trailing and not set(trailing) <= _HARMLESS_TRAILING:
        return None, (f"Invalid JSON inside <{kind}> tags: unexpected content after the "
                      f"object ({trailing.strip()[:40]!r}). Emit one JSON object per block.")
    return payload, None


def parse_actions(llm_response):
    """Extract opcode blocks in document order.

    Each entry: {kind, raw, payload, error}. A block that will not parse is
    returned with error set rather than dropped, so the loop can tell the model
    what went wrong instead of silently doing nothing.
    """
    actions = []
    for match in BLOCK_PATTERN.finditer(llm_response or ""):
        kind, body = match.group(1), match.group(2)
        entry = {"kind": kind, "raw": body.strip(), "payload": None, "error": None}
        payload, error = _decode_payload(body, kind)
        entry["payload"], entry["error"] = payload, error
        actions.append(entry)
    return actions


def _describe(action):
    payload = action.get("payload") or {}
    if action["kind"] == "tool":
        return f"tool:{payload.get('name', '?')}"
    if action["kind"] == "memory":
        args = payload.get("args") if isinstance(payload.get("args"), dict) else payload
        return f"memory:{payload.get('action', '?')}:{args.get('scope', args.get('kind', ''))}".rstrip(":")
    return f"task:{payload.get('action', '?')}"


def _looks_like_failure(result):
    """Did this single action fail?

    Deliberately narrow. It matches ALLAN's own bracketed error prefixes and
    explicit JSON failure fields -- not any occurrence of the word "error",
    which would flag a perfectly good web_search result about error messages.
    """
    if result is None:
        return True
    text = str(result)
    if re.search(r"\[(?:PARSER|MEMORY|TOOL|TASK)[A-Z ]*ERROR\]", text):
        return True
    if re.search(r"\[(?:TOOL CRASH|PERMISSION DENIED|TOOL CALLER ERROR)\]", text):
        return True
    return bool(re.search(r'"(?:error|deleted)"\s*:\s*(?:"|false)', text)) or '"reason": "not_found"' in text


def _route(action, agent_id):
    """Send one parsed block to its handler."""
    payload = action["payload"]
    kind = action["kind"]

    if kind == "task":
        return call_task(payload, agent_id)

    if kind == "memory":
        return call_memory(payload, agent_id)

    # kind == "tool". Memory is a separate opcode and must never arrive here.
    if payload.get("name") == "memory":
        return ("[MEMORY ERROR]: Invalid memory call format. Memory operations must use "
                "<memory>...</memory> and never be wrapped in <tool>.")
    if payload.get("name") == "task":
        return ("[TASK ERROR]: Invalid task call format. Task operations must use "
                "<task>...</task> and never be wrapped in <tool>.")
    # Tolerate a memory-shaped payload that landed in a <tool> tag.
    if "action" in payload or payload.get("name") in MEMORY_ACTION_NAMES:
        return call_memory(payload, agent_id)
    return call_tool(payload, agent_id)


def execute_actions(actions, agent_id="ALLAN_Prime"):
    """Run parsed actions in order, stopping at the first failure.

    Stopping matters because a step may pair real work with its bookkeeping:

        <memory>{"action": "write", ...}</memory>
        <task>{"action": "done", "args": {"id": "task-2"}}</task>

    If the write fails and we keep going, the task gets marked done for work that
    never happened -- and the run then reports success it did not achieve. The
    remaining actions are reported as skipped so ALLAN can see exactly what did
    and did not run.
    """
    records = []
    halted = False
    for action in actions:
        label = _describe(action)

        if halted:
            records.append({"kind": action["kind"], "label": label, "ok": False,
                            "result": "[SKIPPED]: an earlier action in this step failed, "
                                      "so this one was not executed."})
            continue

        if action.get("error"):
            records.append({"kind": action["kind"], "label": label,
                            "ok": False, "result": f"[PARSER ERROR]: {action['error']}"})
            halted = True
            continue

        try:
            result = _route(action, agent_id)
        except Exception as exc:
            result = f"[TOOL CRASH]: {type(exc).__name__} - {exc}"

        ok = not _looks_like_failure(result)
        records.append({"kind": action["kind"], "label": label, "ok": ok, "result": result})
        if not ok:
            halted = True
    return records


def parse_and_route(llm_response, agent_id="ALLAN_Prime"):
    """Backwards-compatible wrapper: run everything, return one joined string."""
    if llm_response is None:
        return None
    actions = parse_actions(llm_response)
    if not actions:
        return None
    records = execute_actions(actions, agent_id)
    if len(records) == 1:
        return records[0]["result"]
    return " | ".join(str(r["result"]) for r in records)
