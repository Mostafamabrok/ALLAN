import json
import os
import re

from llm_api import call_model
from parser import parse_and_route

# Define storage paths globally
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
HISTORY_FILE = os.path.join(STORAGE_DIR, "allan_prime_history.json")

INTERFACE_RULES = {
    "terminal": {
        "label": "terminal",
        "forbidden": [
            "markdown headings",
            "markdown tables",
            "code fences",
            "emoji",
            "long multi-line blocks",
            "xml-like formatting in user output",
        ],
        "required": [
            "plain text only",
            "short paragraphs",
            "no markdown",
            "no tool tags in user-facing output",
        ],
    },
    "voice": {
        "label": "voice",
        "forbidden": [
            "markdown",
            "bullet lists",
            "tool tags",
            "very long sentences",
            "excessive punctuation",
        ],
        "required": [
            "spoken-language style",
            "brief and natural responses",
            "clear direct answer",
            "no hidden system formatting",
        ],
    },
    "default": {
        "label": "unknown",
        "forbidden": [
            "raw tool tags",
            "internal reasoning leaks",
            "markdown if the interface is plain text",
        ],
        "required": [
            "be interface-aware",
            "follow the current interface constraints",
        ],
    },
}


def get_interface_prompt(interface_name="terminal"):
    interface_type = INTERFACE_RULES.get(interface_name.lower(), INTERFACE_RULES["default"])
    forbidden = ", ".join(interface_type["forbidden"])
    required = ", ".join(interface_type["required"])
    return f"""CURRENT INTERFACE: {interface_type['label']}
You are running on a {interface_type['label']} interface.
Formatting rules for this interface:
- Forbidden: {forbidden}
- Required: {required}
Never output forbidden formatting to the user on this interface.
If a tool result needs to be summarized, do it in the correct format for this interface without exposing internal specs or tool tags.
"""


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
6. After a web_search or web_dive result, summarize what you found in the final user reply instead of saying you are still processing.
7. Always respect the current interface constraints described in the interface instructions.

TOOL FORMAT:
<tool>{"name": "the_tool_name", "args": {"argument_key": "argument_value"}}</tool>

Available Tools:
- web_search: Performs a web search. EXAMPLE: <tool>{"name": "web_search", "args": {"query": "capital of France"}}</tool>.
- web_dive: Fetches and extracts readable text from a specific page URL. EXAMPLE: <tool>{"name": "web_dive", "args": {"url": "https://example.com/topic", "max_chars": 2500}}</tool>.

Only the final user reply should be visible to the user."""


def _empty_history():
    return {"entries": []}


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


def _remove_legacy_thread_files():
    legacy_files = [
        os.path.join(STORAGE_DIR, "internal_chat.txt"),
        os.path.join(STORAGE_DIR, "user_chat.txt"),
    ]
    for file_path in legacy_files:
        if os.path.exists(file_path):
            os.remove(file_path)


def init_storage():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)

    _remove_legacy_thread_files()

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
    append_to_history(text, thread="internal")


def append_to_user_chat(text):
    append_to_history(text, thread="user")


def clear_history():
    _write_history(_empty_history())
    _remove_legacy_thread_files()


def _extract_user_reply(raw_response):
    match = re.search(r'<user_reply>(.*?)</user_reply>', raw_response, re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def _follow_up_after_tool(user_input, tool_result, history_context, interface_name="terminal"):
    prompt = (
        "The tool finished running and gathered fresh information. "
        "Now produce a concise user-facing answer summarizing what it found. "
        "Do not mention hidden reasoning, tool internals, or that you are still processing. "
        "Respect the current interface constraints and respond in <user_reply>...</user_reply> only.\n\n"
        f"User request: {user_input}\n\n"
        f"Tool result:\n{tool_result}"
    )
    thinking, response = call_model(
        prompt=f"{history_context}\n{get_interface_prompt(interface_name)}\nALLAN_INTERNAL:\n{prompt}",
        model_name="claude-sonnet-5",
        max_tokens=1024,
        system_prompt=SYSTEM_PROMPT + "\n" + get_interface_prompt(interface_name),
    )

    if response is None:
        return None

    if thinking:
        append_to_internal_chat(f"[ALLAN INTERNAL THOUGHT]: {thinking}")

    append_to_internal_chat(f"ALLAN_INTERNAL: {response}")

    user_reply = _extract_user_reply(response)
    if user_reply:
        return user_reply

    cleaned_response = re.sub(r'<tool>(.*?)</tool>', '', response, flags=re.DOTALL)
    cleaned_response = re.sub(r'\s+', ' ', cleaned_response).strip()
    if cleaned_response:
        return cleaned_response

    return "I found the relevant information and summarized it above."


def ALLAN_prime(user_input, interface_name="terminal"):
    append_to_user_chat(f"User: {user_input}")

    history = get_history()
    prompt_context = f"{_format_history_for_prompt(history)}\n{get_interface_prompt(interface_name)}\nALLAN_INTERNAL:"

    thinking, response = call_model(
        prompt=prompt_context,
        model_name="claude-sonnet-5",
        max_tokens=1024,
        system_prompt=SYSTEM_PROMPT + "\n" + get_interface_prompt(interface_name),
    )

    if response is None:
        return "System Error: The LLM API failed to return a response."

    if thinking:
        append_to_internal_chat(f"[ALLAN INTERNAL THOUGHT]: {thinking}")

    append_to_internal_chat(f"ALLAN_INTERNAL: {response}")

    tool_result = None
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

    if final_user_reply == "I’m processing that internally before answering." and tool_result is not None:
        follow_up_reply = _follow_up_after_tool(
            user_input,
            tool_result,
            _format_history_for_prompt(get_history()),
            interface_name=interface_name,
        )
        if follow_up_reply:
            final_user_reply = follow_up_reply

    append_to_user_chat(f"ALLAN: {final_user_reply}")
    return final_user_reply