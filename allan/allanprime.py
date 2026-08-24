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

TASKS_FILE = os.path.join(MEMORY_DIR, "task_list.json")


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


def _format_sticky_notes_for_prompt(limit=None):
    sticky_path = os.path.join(MEMORY_DIR, "sticky_notes.json")
    try:
        if not os.path.exists(sticky_path):
            return "ACTIVE STICKY NOTES:\nNone"
        with open(sticky_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return "ACTIVE STICKY NOTES:\nNone"

    notes = payload.get("notes", []) if isinstance(payload, dict) else []
    if not notes:
        return "ACTIVE STICKY NOTES:\nNone"

    ordered = sorted(notes, key=lambda n: str(n.get("updated_at") or n.get("created_at") or ""), reverse=True)
    if limit is not None:
        ordered = ordered[:limit]

    concise = []
    for note in ordered:
        updated = note.get("updated_at") or note.get("created_at") or "unknown"
        text = str(note.get("text") or "").strip()
        if not text:
            continue
        concise.append(f"- {updated}: {text}")

    if not concise:
        return "ACTIVE STICKY NOTES:\nNone"
    return "ACTIVE STICKY NOTES:\n" + "\n".join(concise)


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


def _ensure_task_file():
    os.makedirs(MEMORY_DIR, exist_ok=True)
    if not os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump({"tasks": []}, f, ensure_ascii=False, indent=2)
            f.write("\n")


def _load_task_list():
    _ensure_task_file()
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
            return payload["tasks"]
    except Exception:
        pass
    return []


def _save_task_list(tasks):
    _ensure_task_file()
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump({"tasks": tasks}, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _normalize_task_title(raw_title):
    title = str(raw_title or "").strip()
    title = re.sub(r"^[\-\*•\d\s\.)]+", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _parse_task_candidates(raw_text):
    text = str(raw_text or "").strip()
    if not text:
        return []

    cleaned = text
    for prefix in ["set task list", "set todo list", "task list", "todo list", "tasks:", "todo:", "tasks", "todo"]:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    cleaned = cleaned.strip(":- ")
    if not cleaned:
        return []

    parts = re.split(r"\n|;|\|", cleaned)
    candidates = []
    for part in parts:
        for sub in re.split(r",\s*", part):
            item = _normalize_task_title(sub)
            if item and item.lower() not in {"done", "completed", "finished"}:
                candidates.append(item)
    return candidates


def set_task_list(raw_text_or_list):
    if isinstance(raw_text_or_list, list):
        titles = [str(item).strip() for item in raw_text_or_list if str(item).strip()]
    else:
        titles = _parse_task_candidates(raw_text_or_list)

    tasks = []
    timestamp = datetime.now(timezone.utc).isoformat()
    for index, title in enumerate(titles, start=1):
        tasks.append({
            "id": f"task-{index}",
            "title": title,
            "status": "pending",
            "created_at": timestamp,
            "updated_at": timestamp,
        })

    _save_task_list(tasks)
    return tasks


def list_tasks():
    return _load_task_list()


def get_pending_tasks():
    return [task for task in _load_task_list() if str(task.get("status", "pending")).lower() != "done"]


def has_pending_tasks():
    return bool(get_pending_tasks())


def mark_task_done(selector):
    tasks = _load_task_list()
    if not tasks:
        return None

    if isinstance(selector, int):
        index = selector - 1
        if 0 <= index < len(tasks):
            tasks[index]["status"] = "done"
            tasks[index]["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save_task_list(tasks)
            return tasks[index]
        return None

    selector_norm = str(selector).strip().lower()
    for task in tasks:
        if str(task.get("id", "")).lower() == selector_norm or str(task.get("title", "")).lower() == selector_norm:
            task["status"] = "done"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save_task_list(tasks)
            return task

    try:
        index = int(selector_norm) - 1
        if 0 <= index < len(tasks):
            tasks[index]["status"] = "done"
            tasks[index]["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save_task_list(tasks)
            return tasks[index]
    except ValueError:
        pass

    return None


def clear_tasks():
    _save_task_list([])
    return []


def _format_task_prompt_context():
    tasks = list_tasks()
    if not tasks:
        return "ACTIVE TASK CHAIN:\nNone"

    pending = [task for task in tasks if str(task.get("status", "pending")).lower() != "done"]
    if not pending:
        return "ACTIVE TASK CHAIN:\nAll tasks are complete."

    lines = [f"{index + 1}. {task.get('title')} ({task.get('status', 'pending')})" for index, task in enumerate(tasks)]
    next_task = pending[0].get("title")
    return "ACTIVE TASK CHAIN:\n" + "\n".join(lines) + f"\nNEXT PRIORITY: execute task 1 now: {next_task}. Do not answer with a general summary before working the current task."


def handle_task_command(user_input):
    text = str(user_input or "").strip()
    if not text:
        return None
    lower = text.lower()

    if lower in {"tasks", "list tasks", "show tasks", "task list", "todo list"}:
        tasks = list_tasks()
        if not tasks:
            return "There are no active tasks yet."
        lines = [f"{index + 1}. {task.get('title')} ({task.get('status', 'pending')})" for index, task in enumerate(tasks)]
        return "Current tasks:\n" + "\n".join(lines)

    if lower in {"clear tasks", "clear task list", "reset tasks", "wipe tasks"}:
        clear_tasks()
        return "Task list cleared."

    if lower in {"mark all tasks done", "complete all tasks", "finish all tasks"}:
        tasks = _load_task_list()
        for task in tasks:
            task["status"] = "done"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_task_list(tasks)
        return "All tasks marked as done."

    if re.match(r"^(mark\s+)?(task|todo)\s+.*\s+(done|complete|finished)$", lower):
        match = re.match(r"^(?:mark\s+)?(?:task|todo)\s+(.+?)\s+(?:done|complete|finished)$", text, flags=re.IGNORECASE)
        if match:
            target = match.group(1).strip()
            task = mark_task_done(target)
            if task:
                return f"Marked task as done: {task.get('title')}"
            return f"I could not find the task '{target}' to mark done."

    if re.match(r"^(set|create)\s+(task|todo)\s+list\s*[:\-]?\s*", text, flags=re.IGNORECASE) or "task list" in lower or "todo list" in lower or lower.startswith("tasks:") or lower.startswith("todo:"):
        tasks = set_task_list(text)
        if not tasks:
            return "I did not find any tasks to set."
        summary = "Task list set:\n" + "\n".join(f"{index + 1}. {task['title']}" for index, task in enumerate(tasks))
        return summary

    return None


def clear_history():
    _write_history(_empty_history())
    _remove_legacy_thread_files()


def _extract_user_reply(raw_response):
    match = re.search(r'<user_reply>(.*?)</user_reply>', raw_response, re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def _is_tool_or_memory_turn(raw_response):
    return bool(re.search(r'<(?:tool|memory)>.*?</(?:tool|memory)>', raw_response, re.DOTALL))


def _collapse_to_tool_blocks(raw_response):
    if raw_response is None:
        return ""
    blocks = []
    for kind in ("tool", "memory"):
        for block in re.findall(rf'<{kind}>(.*?)</{kind}>', raw_response, re.DOTALL):
            blocks.append(f"<{kind}>{block}</{kind}>")
    return "\n".join(blocks)


def _route_result_has_failure(route_result):
    if route_result is None:
        return False
    text = str(route_result)
    if re.search(r"\[(?:PARSER|MEMORY|TOOL) ERROR\]", text, flags=re.IGNORECASE):
        return True
    lower = text.lower()
    return '"error"' in lower or '"deleted": false' in lower or '"reason": "not_found"' in lower


def _build_internal_decision_prompt(user_input, history_context, sticky_context, task_context, interface_name="terminal"):
    return (
        "You are in the ALLAN internal decision phase. "
        "Your job is to decide whether the next step is a tool call, a memory operation, or a direct user-facing answer. "
        "Do not write a user-facing response yet. Do not narrate your reasoning. "
        "Choose exactly one action and emit only that action in a single turn.\n\n"
        "Allowed outputs:\n"
        "1) <tool>{\"name\": \"...\", ...}</tool>\n"
        "2) <memory>{\"action\": \"...\", \"args\": {...}}</memory>\n"
        "3) <user_reply>final answer or brief clarifying question</user_reply>\n\n"
        "Rules:\n"
        "- If you need external information, emit <tool> or <memory> only.\n"
        "- If no external information is needed, emit <user_reply> only.\n"
        "- Never mix a tool block and a user reply in the same output.\n"
        "- Never claim a tool or memory action succeeded without fresh execution and verification.\n"
        "- If the user request is ambiguous, ask for the missing fact in <user_reply> only.\n"
        "- Respect the active interface formatting rules.\n\n"
        f"User request: {user_input}\n\n"
        f"History:\n{history_context}\n\n"
        f"Sticky notes:\n{sticky_context}\n\n"
        f"Task context:\n{task_context}\n\n"
        f"Interface:\n{get_interface_prompt(interface_name)}"
    )


def _run_internal_decision(user_input, interface_name="terminal"):
    history = get_history()
    sticky_context = _format_sticky_notes_for_prompt()
    task_context = _format_task_prompt_context()
    history_context = _format_history_for_prompt(history)
    prompt = _build_internal_decision_prompt(user_input, history_context, sticky_context, task_context, interface_name)
    thinking, response = call_model(
        prompt=prompt,
        model_name=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system_prompt=SYSTEM_PROMPT + "\n" + get_interface_prompt(interface_name),
    )
    if thinking:
        append_to_internal_chat(f"[ALLAN INTERNAL THOUGHT]: {thinking}")
    if response is None:
        return ""
    append_to_internal_chat(f"ALLAN_INTERNAL_DECISION: {response}")
    return response


def _generate_user_reply(user_input, context_text, interface_name="terminal"):
    sticky_context = _format_sticky_notes_for_prompt()
    prompt = (
        "You are in the ALLAN user-delivery phase. "
        "Produce only the final user-facing answer for the user. "
        "Do not include tool tags, memory tags, raw parser output, or internal reasoning. "
        "Do not mention that you are thinking or that you are self-prompting. "
        "Respond in the interface style requested by the user, and keep it concise.\n\n"
        f"User request: {user_input}\n\n"
        f"Fresh context:\n{context_text}\n\n"
        f"Sticky notes:\n{sticky_context}\n\n"
        f"Interface:\n{get_interface_prompt(interface_name)}"
    )
    thinking, response = call_model(
        prompt=prompt,
        model_name=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system_prompt=SYSTEM_PROMPT + "\n" + get_interface_prompt(interface_name),
    )
    if thinking:
        append_to_internal_chat(f"[ALLAN INTERNAL THOUGHT]: {thinking}")
    if response is None:
        return None
    append_to_internal_chat(f"ALLAN_USER_RESPONSE_DRAFT: {response}")
    user_reply = _extract_user_reply(response)
    if user_reply:
        return user_reply
    cleaned = re.sub(r'<(?:tool|memory)>(.*?)</(?:tool|memory)>', '', response, flags=re.DOTALL)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned:
        return cleaned
    return None


def _follow_up_after_tool(user_input, tool_result, history_context, interface_name="terminal"):
    context = (
        f"The tool finished running and gathered fresh information.\n"
        f"User request: {user_input}\n\n"
        f"Tool result:\n{tool_result}\n\n"
        f"History:\n{history_context}"
    )
    return _generate_user_reply(user_input, context, interface_name=interface_name)


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
            if os.path.exists(TASKS_FILE):
                try:
                    os.remove(TASKS_FILE)
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

    decision_response = _run_internal_decision(user_input, interface_name=interface_name)
    if not decision_response:
        return "System Error: The LLM API failed to return a decision response."

    if _is_tool_or_memory_turn(decision_response):
        decision_response = _collapse_to_tool_blocks(decision_response)

    route_result = None
    tool_was_used = False
    if re.search(r'<(?:tool|memory)>(.*?)</(?:tool|memory)>', decision_response, re.DOTALL):
        tool_was_used = True
        route_result = parse_and_route(decision_response, agent_id="ALLAN_Prime")
        if route_result:
            append_to_internal_chat(f"[SYSTEM TOOL EXECUTION]: {route_result}")

    if _route_result_has_failure(route_result):
        final_user_reply = "The previous tool or memory call failed, so no action was executed."
        append_to_internal_chat(f"[SYSTEM TOOL EXECUTION FAILURE]: {route_result}")
        append_to_user_chat(f"ALLAN: {final_user_reply}")
        return final_user_reply

    task_command_result = handle_task_command(user_input)
    if task_command_result is not None and not tool_was_used:
        append_to_internal_chat(f"[TASK SYSTEM]: {task_command_result}")
        final_user_reply = task_command_result
        append_to_user_chat(f"ALLAN: {final_user_reply}")
        return final_user_reply

    user_reply = _extract_user_reply(decision_response)
    if user_reply:
        final_user_reply = user_reply
    elif tool_was_used and route_result is not None:
        follow_up_reply = _follow_up_after_tool(
            user_input,
            route_result,
            _format_history_for_prompt(get_history()),
            interface_name=interface_name,
        )
        final_user_reply = follow_up_reply or "I’ve completed the internal check and am ready to answer."
    else:
        final_user_reply = _generate_user_reply(
            user_input,
            _format_history_for_prompt(get_history()),
            interface_name=interface_name,
        ) or "I’m processing that internally before answering."

    append_to_user_chat(f"ALLAN: {final_user_reply}")
    return final_user_reply