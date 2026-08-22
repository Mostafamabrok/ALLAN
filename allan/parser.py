import re
import json
from tool_caller import call_tool

def parse_and_route(llm_response, agent_id="ALLAN_Prime"):
    #Scans raw text for tool calls and routes them to the Tool Caller.
    
    match = re.search(r'<tool>(.*?)</tool>', llm_response, re.DOTALL)
    
    if match:
        try:
            tool_request = json.loads(match.group(1))
            # Hand off to the Big Brother
            return call_tool(tool_request, agent_id)
        except json.JSONDecodeError:
            return "[PARSER ERROR]: Invalid JSON format inside tool tags."
            
    return None # No tool requested