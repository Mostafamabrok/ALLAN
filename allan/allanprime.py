import json
import os
import re

from llm_api import call_model
from parser import parse_and_route

# Define storage paths globally
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
RAW_CONTEXT_DIR = os.path.join(STORAGE_DIR, "raw_agent_context")
MEMORY_DIR = os.path.join(STORAGE_DIR, "memory")
HISTORY_FILE = os.path.join(RAW_CONTEXT_DIR, "allan_prime.json")
GENERAL_SUMMARY_FILE = os.path.join(MEMORY_DIR, "general_summarized_event_list.json")

# Interface rules are loaded from settings (Allan_Prime_Settings.json) to avoid duplication.
# The settings file (created by setup.py) provides the authoritative interface rules.
INTERFACE_RULES = {}


def get_interface_prompt(interface_name="terminal"):
    interface_type = INTERFACE_RULES.get(interface_name.lower(), INTERFACE_RULES.get("default", {}))
    forbidden = ", ".join(interface_type.get("forbidden", []))
    required = ", ".join(interface_type.get("required", []))
    return f"""CURRENT INTERFACE: {interface_type.get('label','unknown')}
You are running on a {interface_type.get('label','unknown')} interface.
Formatting rules for this interface:
- Forbidden: {forbidden}
- Required: {required}
Never output forbidden formatting to the user on this interface.
If a tool result needs to be summarized, do it in the correct format for this interface without exposing internal specs or tool tags.
"""


# Minimal fallback system prompt; the real prompt should come from Allan_Prime_Settings.json
SYSTEM_PROMPT = "You are ALLAN. Use private internal reasoning, call tools in internal mode, and produce a single user-facing reply. Settings can override this prompt."

# Load external settings if present (created by setup.py)
SETTINGS_FILE = os.path.join(BASE_DIR, "Allan_Prime_Settings.json")
SETTINGS = {}
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as sf:
            SETTINGS = json.load(sf)
    except Exception:
        SETTINGS = {}

# Load required settings from the settings file. Fail fast if they are missing.
INTERFACE_RULES = SETTINGS.get("interface_rules")
if INTERFACE_RULES is None:
    raise RuntimeError(
        "Missing 'interface_rules' in Allan_Prime_Settings.json — run allan/setup.py to create default settings."
    )

SYSTEM_PROMPT = SETTINGS.get("system_prompt")
if SYSTEM_PROMPT is None:
    raise RuntimeError(
        "Missing 'system_prompt' in Allan_Prime_Settings.json — run allan/setup.py to create default settings."
    )

MODEL_NAME = SETTINGS.get("model_name")
if not MODEL_NAME:
    raise RuntimeError(
        "Missing 'model_name' in Allan_Prime_Settings.json — run allan/setup.py to create default settings."
    )

MAX_TOKENS = SETTINGS.get("max_tokens")
if not isinstance(MAX_TOKENS, int):
    raise RuntimeError(
        "Missing or invalid 'max_tokens' (integer) in Allan_Prime_Settings.json — run allan/setup.py to create default settings."
    )


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
        # If the JSON is malformed, attempt to return the raw file contents as a single legacy entry.
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as lf:
                legacy_text = lf.read().strip()
        except Exception:
            legacy_text = ""

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
        os.path.join(STORAGE_DIR, "allan_prime_history.json"),
    ]
    for file_path in legacy_files:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


def init_storage():
    # Ensure base storage and subfolders
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)
    if not os.path.exists(RAW_CONTEXT_DIR):
        os.makedirs(RAW_CONTEXT_DIR)
    if not os.path.exists(MEMORY_DIR):
        os.makedirs(MEMORY_DIR)

    # remove old legacy files
    _remove_legacy_thread_files()

    # Migrate any old history file into new raw context location if present
    old_history = os.path.join(STORAGE_DIR, "allan_prime_history.json")
    if os.path.exists(old_history) and not os.path.exists(HISTORY_FILE):
        try:
            os.replace(old_history, HISTORY_FILE)
        except Exception:
            pass

    # Ensure history files exist and are valid json
    if not os.path.exists(HISTORY_FILE) or os.path.getsize(HISTORY_FILE) == 0:
        _write_history(_empty_history())

    if not os.path.exists(GENERAL_SUMMARY_FILE) or os.path.getsize(GENERAL_SUMMARY_FILE) == 0:
        with open(GENERAL_SUMMARY_FILE, "w", encoding="utf-8") as f:
            json.dump({"summaries": []}, f, ensure_ascii=False, indent=2)
            f.write("\n")


def get_history():
    return _load_history()


from datetime import datetime, timezone


def append_to_history(text, thread="system", called_tools=None):
    """Append a history entry with id, timestamp, thread, text, and optional called_tools.

    called_tools should be a list of dictionaries: [{"name": ..., "args": {...}}]
    """
    history = _load_history()
    entries = history.setdefault("entries", [])

    # determine next id
    next_id = 1
    if entries:
        try:
            max_id = max(int(e.get("id", 0)) for e in entries)
            next_id = max_id + 1
        except Exception:
            next_id = len(entries) + 1

    timestamp = datetime.now(timezone.utc).isoformat()

    entry = {
        "id": next_id,
        "thread": thread,
        "timestamp": timestamp,
        "text": text,
    }
    if called_tools:
        entry["called_tools"] = called_tools

    entries.append(entry)
    _write_history(history)


def append_to_internal_chat(text, called_tools=None):
    append_to_history(text, thread="internal", called_tools=called_tools)


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
        model_name=MODEL_NAME,
        max_tokens=MAX_TOKENS,
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
    # Temporary feature: Full clear wipe all memory when the user requests it explicitly.
    if isinstance(user_input, str) and user_input.strip().lower() == "full clear":
        # remove raw context and memory dirs
        try:
            if os.path.exists(RAW_CONTEXT_DIR):
                for fname in os.listdir(RAW_CONTEXT_DIR):
                    try:
                        os.remove(os.path.join(RAW_CONTEXT_DIR, fname))
                    except Exception:
                        pass
            if os.path.exists(MEMORY_DIR):
                for fname in os.listdir(MEMORY_DIR):
                    try:
                        os.remove(os.path.join(MEMORY_DIR, fname))
                    except Exception:
                        pass
            # rewrite empty history and summary files
            _write_history(_empty_history())
            with open(GENERAL_SUMMARY_FILE, "w", encoding="utf-8") as f:
                json.dump({"summaries": []}, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception:
            pass
        return "All memory cleared. (raw histories and summaries wiped)"

    append_to_user_chat(f"User: {user_input}")

    history = get_history()
    prompt_context = f"{_format_history_for_prompt(history)}\n{get_interface_prompt(interface_name)}\nALLAN_INTERNAL:"

    thinking, response = call_model(
        prompt=prompt_context,
        model_name=MODEL_NAME,
        max_tokens=MAX_TOKENS,
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