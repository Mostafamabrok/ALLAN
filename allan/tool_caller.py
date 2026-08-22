import io
import os
import importlib.util
from contextlib import redirect_stdout, redirect_stderr

# Mock permissions table: Define which agents can run which tools
AGENT_PERMISSIONS = {
    "ALLAN_Prime": ["*"],  # Prime has root access
    "sub_agent_researcher": ["web_search", "read_file"],
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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