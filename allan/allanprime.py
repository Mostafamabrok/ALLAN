import os
from llm_api import call_model
from parser import parse_and_route

# Define storage paths globally
STORAGE_DIR = "storage"
HISTORY_FILE = os.path.join(STORAGE_DIR, "allan_prime_history.txt")


SYSTEM_PROMPT = """You are ALLAN (Autonomous Language Learning Agent Network), an advanced, highly capable AI assistant. 
You act as the primary orchestrator of a multi-agent system, maintaining persistent memory across sessions.

TOOL USAGE PROTOCOL:
If you need to interact with the system, perform a task, or retrieve data, you MUST use a tool. 
To call a tool, output a JSON object wrapped in exact <tool> tags. 

Format:
<tool>{"name": "the_tool_name", "args": {"argument_key": "argument_value"}}</tool>

Available Tools:
- web_search: Performs a web search. EXAMPLE: <tool>{"name": "web_search", "args": {"query": "capital of France"}}</tool>.

Do not add extra text inside the tags. The system will execute the tool and return the result to you."""


def init_storage():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w") as f:
            pass

def get_history():
    with open(HISTORY_FILE, "r") as f:
        return f.read().strip()

def append_to_history(text):
    with open(HISTORY_FILE, "a") as f:
        f.write(text + "\n")

def clear_history():
    with open(HISTORY_FILE, "w") as f:
        pass

def ALLAN_prime(user_input):

    append_to_history(f"User: {user_input}")
    
    full_history = get_history()
    prompt_context = f"{full_history}\nALLAN:"
    
    # Pass the SYSTEM_PROMPT into the LLM call
    thinking, response = call_model(
        prompt=prompt_context, 
        model_name="claude-sonnet-5", 
        max_tokens=1024,
        system_prompt=SYSTEM_PROMPT
    )
    
    if response is None:
        return "System Error: The LLM API failed to return a response."
    
    if thinking:
        append_to_history(f"[ALLAN INTERNAL THOUGHT]: {thinking}")
            
    append_to_history(f"ALLAN: {response}")

    # Tool routing
    tool_result = parse_and_route(response, agent_id="ALLAN_Prime")
    
    if tool_result:
        append_to_history(f"[SYSTEM TOOL EXECUTION]: {tool_result}")
        response += f"\n\n[System Execution]: {tool_result}"

    return response