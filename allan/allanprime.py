import json
import os
import re

from llm_api import call_model
from parser import parse_and_route

# Define storage paths globally
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
HISTORY_FILE = os.path.join(STORAGE_DIR, "allan_prime_history.json")
INTERNAL_CHAT_FILE = os.path.join(STORAGE_DIR, "internal_chat.txt")
USER_CHAT_FILE = os.path.join(STORAGE_DIR, "user_chat.txt")

SYSTEM_PROMPT = """You are ALLAN (Autonomous Language Learning Agent Network), an advanced, highly capable AI assistant.
You maintain two conversation threads:
- internal_chat: private reasoning, tool decisions, and system state. This is never shown to the user.
- user_chat: the visible conversation with the user. Only the final user-facing message belongs here.

RULES:
1. Do all work and tool logic in the internal thread before deciding the user-facing answer.
2. If you need to interact with the system, output a tool call in exact <tool> tags in the internal stream.
3. When you are ready to speak to the user, wrap the final visible response in <user_reply> ... </user_reply>.
4. Do not expose hidden reasoning to the user.
5. If no tool is needed, still provide the answer in <user_reply> ... </user_reply>.

TOOL FORMAT:
<tool>{"name": "the_tool_name", "args": {"argument_key": "argument_value"}}</tool>

Available Tools:
- web_search: Performs a web search. EXAMPLE: <tool>{"name": "web_search", "args": {"query": "capital of France"}}</tool>.

Only the final user reply should be visible to the user."""


def _empty_history():
    return {"entries": []}


def _read_thread(file_path):
    if not os.path.exists(file_path):
        return ""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _append_to_thread(file_path, text):
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def _write_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _load_history():
    if not os.path.exists(HISTORY_FILE):
        return _empty_history()

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return _empty_history()

        payload = json.loads(raw)
        if isinstance(payload, dict) and "entries" in payload:
            return payload
        if isinstance(payload, list):
            return {"entries": [{"thread": "legacy", "text": str(item)} for item in payload]}
        return _empty_history()
    except (json.JSONDecodeError, TypeError, ValueError):
        legacy_text = _read_thread(HISTORY_FILE)
        if not legacy_text:
            return _empty_history()
        return {"entries": [{"thread": "legacy", "text": legacy_text}]}


def _format_history_for_prompt(history):
    entries = history.get("entries", [])
    if not entries:
        return ""

    formatted = []
    for entry in entries:
        thread = entry.get("thread", "unknown")
        text = entry.get("text", "")
        formatted.append(f"[{thread}] {text}")
    return "\n".join(formatted)


def init_storage():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)

    for file_path in (HISTORY_FILE, INTERNAL_CHAT_FILE, USER_CHAT_FILE):
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                pass

    if not os.path.exists(HISTORY_FILE) or os.path.getsize(HISTORY_FILE) == 0:
        _write_history(_empty_history())


def get_history():
    return _load_history()


def append_to_history(text, thread="system"):
    history = _load_history()
    history.setdefault("entries", []).append({
        "thread": thread,
        "text": text,
    })
    _write_history(history)


def append_to_internal_chat(text):
    _append_to_thread(INTERNAL_CHAT_FILE, text)
    append_to_history(text, thread="internal")


def append_to_user_chat(text):
    _append_to_thread(USER_CHAT_FILE, text)
    append_to_history(text, thread="user")


def clear_history():
    _write_history(_empty_history())

    for file_path in (INTERNAL_CHAT_FILE, USER_CHAT_FILE):
        with open(file_path, "w", encoding="utf-8") as f:
            pass


def _extract_user_reply(raw_response):
    match = re.search(r'<user_reply>(.*?)</user_reply>', raw_response, re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def ALLAN_prime(user_input):
    append_to_user_chat(f"User: {user_input}")

    history = get_history()
    prompt_context = f"{_format_history_for_prompt(history)}\nALLAN_INTERNAL:"

    thinking, response = call_model(
        prompt=prompt_context,
        model_name="claude-sonnet-5",
        max_tokens=1024,
        system_prompt=SYSTEM_PROMPT,
    )

    if response is None:
        return "System Error: The LLM API failed to return a response."

    if thinking:
        append_to_internal_chat(f"[ALLAN INTERNAL THOUGHT]: {thinking}")

    append_to_internal_chat(f"ALLAN_INTERNAL: {response}")

    # Tool routing happens in the internal thread before the final user answer is chosen.
    tool_match = re.search(r'<tool>(.*?)</tool>', response, re.DOTALL)
    if tool_match:
        tool_result = parse_and_route(response, agent_id="ALLAN_Prime")
        if tool_result:
            cleaned_response = response[:tool_match.start()] + response[tool_match.end():]
            cleaned_response = re.sub(r"\s+", " ", cleaned_response).strip()
            append_to_internal_chat(f"[SYSTEM TOOL EXECUTION]: {tool_result}")
            response = cleaned_response

    user_reply = _extract_user_reply(response)
    if user_reply:
        final_user_reply = user_reply
    else:
        final_user_reply = re.sub(r"\s+", " ", response).strip()

    if not final_user_reply:
        final_user_reply = "I’m processing that internally before answering."

    append_to_user_chat(f"ALLAN: {final_user_reply}")
    return final_user_reply