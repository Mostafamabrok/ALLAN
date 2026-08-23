import json
import re

from memory import call_memory
from tool_caller import call_tool


def _route_memory_or_tool(request_obj, agent_id):
    if not isinstance(request_obj, dict):
        return "[PARSER ERROR]: Memory/tool payload was not valid JSON object."

    # Memory is a separate opcode. Never route it through the normal tool system.
    if request_obj.get("name") == "memory":
        return (
            "[MEMORY ERROR]: Invalid memory call format. "
            "Memory operations must use <memory>...</memory> and never be wrapped in <tool>."
        )

    # Detect likely memory-op payloads and route them to memory handling.
    if "action" in request_obj or request_obj.get("name") in {
        "search",
        "retrieve",
        "read",
        "write",
        "rewrite",
        "update",
        "delete",
        "find",
    } or "type" in request_obj:
        return call_memory(request_obj, agent_id)

    return call_tool(request_obj, agent_id)


def parse_and_route(llm_response, agent_id="ALLAN_Prime"):
    """Scan a model response for tool calls and memory calls and route them."""
    if llm_response is None:
        return None

    results = []

    memory_matches = re.findall(r'<memory>(.*?)</memory>', llm_response, re.DOTALL)
    for block in memory_matches:
        try:
            memory_request = json.loads(block)
            results.append(_route_memory_or_tool(memory_request, agent_id))
        except json.JSONDecodeError:
            results.append("[PARSER ERROR]: Invalid JSON format inside memory tags.")

    tool_matches = re.findall(r'<tool>(.*?)</tool>', llm_response, re.DOTALL)
    for block in tool_matches:
        try:
            tool_request = json.loads(block)
            results.append(_route_memory_or_tool(tool_request, agent_id))
        except json.JSONDecodeError:
            results.append("[PARSER ERROR]: Invalid JSON format inside tool tags.")

    if not results:
        return None

    if len(results) == 1:
        return results[0]

    return " | ".join(str(item) for item in results)
