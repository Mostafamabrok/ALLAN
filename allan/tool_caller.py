import io
import os
import json
import importlib.util
from contextlib import redirect_stdout, redirect_stderr

# Mock permissions table: Define which agents can run which tools
AGENT_PERMISSIONS = {
    "ALLAN_Prime": ["*"],  # Prime has root access
    "sub_agent_researcher": ["web_search", "web_dive", "read_file"],
}

from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "storage", "raw_agent_context", "allan_prime.json")


def _append_history_entry(text, thread="internal", called_tools=None):
    # Minimal local history append to avoid importing allanprime (prevents circular import)
    try:
        if not os.path.exists(HISTORY_FILE):
            # create minimal history
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                f.write('{"entries": []}\n')
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            payload = {"entries": []}
            try:
                if raw:
                    payload = json.loads(raw)
            except Exception:
                payload = {"entries": [{"thread": "legacy", "text": raw}]} if raw else {"entries": []}

        entries = payload.setdefault("entries", [])
        next_id = 1
        if entries:
            try:
                max_id = max(int(e.get("id", 0)) for e in entries)
                next_id = max_id + 1
            except Exception:
                next_id = len(entries) + 1
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {"id": next_id, "thread": thread, "timestamp": timestamp, "text": text}
        if called_tools:
            entry["called_tools"] = called_tools
        entries.append(entry)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception:
        pass


def check_permissions(tool_name, agent_id):
    """Verifies if an agent is allowed to execute a specific tool."""
    allowed_tools = AGENT_PERMISSIONS.get(agent_id, [])
    return "*" in allowed_tools or tool_name in allowed_tools


def call_tool(tool_request, agent_id):
    """Acts as the execution hub. Checks permissions and runs external tool files."""
    tool_name = tool_request.get("name")
    tool_args = tool_request.get("args", {})

    if not tool_name:
        return "[TOOL CALLER ERROR]: Malformed tool request, missing name."

    # 1. Security Check
    if not check_permissions(tool_name, agent_id):
        return f"[PERMISSION DENIED]: Agent '{agent_id}' cannot access '{tool_name}'."

    # 2. Locate the Tool File
    tool_path = os.path.join(BASE_DIR, "tool_library", f"{tool_name}.py")
    if not os.path.exists(tool_path):
        return f"[TOOL ERROR]: Script '{tool_name}.py' not found in tool_library/."

    # 3. Dynamic Execution
    try:
        # Record the tool invocation in history (arguments only; no result)
        try:
            called_tools = [{"name": tool_name, "args": tool_args}]
            _append_history_entry(f"Tool invoked: {tool_name}", thread="internal", called_tools=called_tools)
        except Exception:
            pass

        spec = importlib.util.spec_from_file_location(tool_name, tool_path)
        if spec is None or spec.loader is None:
            return f"[TOOL ERROR]: Unable to load '{tool_name}.py'."

        tool_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool_module)

        # Quietly capture any tool stdout so it does not leak into the caller stack.
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            result = tool_module.run(**tool_args)

        if result is None:
            result = "Tool completed without returning a value."

        return f"[{tool_name} SUCCESS]: {result}"

    except Exception as e:
        return f"[TOOL CRASH]: Error executing '{tool_name}.py' - {str(e)}"