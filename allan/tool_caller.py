import os
import importlib.util

# Mock permissions table: Define which agents can run which tools
AGENT_PERMISSIONS = {
    "ALLAN_Prime": ["*"], # Prime has root access
    "sub_agent_researcher": ["web_search", "read_file"]
}

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
    tool_path = os.path.join("tool_library", f"{tool_name}.py")
    if not os.path.exists(tool_path):
        return f"[TOOL ERROR]: Script '{tool_name}.py' not found in tool_library/."

    # 3. Dynamic Execution
    try:
        # Dynamically load the tool module from the file path
        spec = importlib.util.spec_from_file_location(tool_name, tool_path)
        tool_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool_module)
        
        # Contract: Every tool in the library MUST have a main run() function
        result = tool_module.run(**tool_args)
        return f"[{tool_name} SUCCESS]: {result}"
        
    except Exception as e:
        return f"[TOOL CRASH]: Error executing '{tool_name}.py' - {str(e)}"