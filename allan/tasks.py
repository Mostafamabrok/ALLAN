"""Task chain state for ALLAN.

The task list is control state for the agent loop, not a narrative. It lives in
its own module so both the loop (allanprime) and the opcode router (parser) can
reach it without importing each other.

Two ways in:
  - the <task> opcode, which ALLAN itself emits during a loop run
  - the plain-text commands a user types, handled in allanprime

Before this module existed only the second path worked, so the loop could
create a task chain but never advance it.
"""

import json
import os
import re
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(BASE_DIR, "storage", "memory")
TASKS_FILE = os.path.join(MEMORY_DIR, "task_list.json")

TERMINAL_STATUSES = {"done", "failed", "skipped"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure_task_file():
    os.makedirs(MEMORY_DIR, exist_ok=True)
    if not os.path.exists(TASKS_FILE):
        _save_task_list([])


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
    os.makedirs(MEMORY_DIR, exist_ok=True)
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
    for prefix in ["set task list", "set todo list", "task list", "todo list",
                   "tasks:", "todo:", "tasks", "todo"]:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    cleaned = cleaned.strip(":- ")
    if not cleaned:
        return []

    candidates = []
    for part in re.split(r"\n|;|\|", cleaned):
        for sub in re.split(r",\s*", part):
            item = _normalize_task_title(sub)
            if item and item.lower() not in {"done", "completed", "finished"}:
                candidates.append(item)
    return candidates


def _next_task_id(tasks):
    highest = 0
    for task in tasks:
        match = re.match(r"task-(\d+)$", str(task.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"task-{highest + 1}"


def set_task_list(raw_text_or_list):
    """Replace the whole chain."""
    if isinstance(raw_text_or_list, list):
        titles = [_normalize_task_title(t) for t in raw_text_or_list]
        titles = [t for t in titles if t]
    else:
        titles = _parse_task_candidates(raw_text_or_list)

    stamp = _now()
    tasks = [
        {"id": f"task-{i}", "title": title, "status": "pending",
         "notes": [], "created_at": stamp, "updated_at": stamp}
        for i, title in enumerate(titles, start=1)
    ]
    _save_task_list(tasks)
    return tasks


def add_task(title):
    title = _normalize_task_title(title)
    if not title:
        return None
    tasks = _load_task_list()
    stamp = _now()
    task = {"id": _next_task_id(tasks), "title": title, "status": "pending",
            "notes": [], "created_at": stamp, "updated_at": stamp}
    tasks.append(task)
    _save_task_list(tasks)
    return task


def list_tasks():
    return _load_task_list()


def get_pending_tasks():
    return [t for t in _load_task_list()
            if str(t.get("status", "pending")).lower() not in TERMINAL_STATUSES]


def has_pending_tasks():
    return bool(get_pending_tasks())


def current_task():
    """The earliest task that is not finished -- the loop's current objective."""
    pending = get_pending_tasks()
    return pending[0] if pending else None


def _find_task(tasks, selector):
    """Resolve a task by id, 1-based position, or exact title."""
    if selector is None:
        return None
    key = str(selector).strip().lower()
    if not key:
        return None

    for task in tasks:
        if str(task.get("id", "")).lower() == key:
            return task
    for task in tasks:
        if str(task.get("title", "")).strip().lower() == key:
            return task
    try:
        index = int(key) - 1
        if 0 <= index < len(tasks):
            return tasks[index]
    except ValueError:
        pass
    return None


def set_task_status(selector, status):
    tasks = _load_task_list()
    task = _find_task(tasks, selector)
    if task is None:
        return None
    task["status"] = str(status).lower()
    task["updated_at"] = _now()
    _save_task_list(tasks)
    return task


def mark_task_done(selector):
    return set_task_status(selector, "done")


def add_task_note(selector, text):
    """Attach a finding to a task so it survives into later steps and turns."""
    text = str(text or "").strip()
    if not text:
        return None
    tasks = _load_task_list()
    task = _find_task(tasks, selector)
    if task is None:
        return None
    task.setdefault("notes", []).append({"text": text, "created_at": _now()})
    task["updated_at"] = _now()
    _save_task_list(tasks)
    return task


def clear_tasks():
    _save_task_list([])
    return []


def format_task_state(include_notes=True):
    """Render the chain for a prompt. Deterministic -- safe inside a cached prefix."""
    tasks = list_tasks()
    if not tasks:
        return "TASK CHAIN: empty. If this request needs multiple steps, set one now."

    lines = []
    for index, task in enumerate(tasks, start=1):
        status = str(task.get("status", "pending")).lower()
        marker = "x" if status == "done" else ("!" if status == "failed" else " ")
        lines.append(f"  [{marker}] {index}. ({task.get('id')}) {task.get('title')} -- {status}")
        if include_notes:
            for note in task.get("notes", []):
                lines.append(f"        note: {note.get('text')}")

    pending = get_pending_tasks()
    if not pending:
        footer = "All tasks are finished. Deliver the final answer to the user now."
    else:
        footer = (
            f"CURRENT OBJECTIVE: {pending[0].get('id')} -- {pending[0].get('title')}\n"
            "Work this task now. Mark it done when it is genuinely complete, then continue."
        )
    return "TASK CHAIN:\n" + "\n".join(lines) + "\n" + footer


# --------------------------------------------------------------------------
# <task> opcode
# --------------------------------------------------------------------------

def call_task(request, agent_id="ALLAN_Prime"):
    """Handle a <task> block. Returns a JSON string, mirroring call_memory."""
    if isinstance(request, str):
        try:
            request = json.loads(request)
        except Exception:
            return "[TASK ERROR]: Invalid task request JSON."
    if not isinstance(request, dict):
        return "[TASK ERROR]: Task request must be a JSON object."

    action = request.get("action") or request.get("name")
    payload = request.get("args") if isinstance(request.get("args"), dict) else request
    if action is None:
        return "[TASK ERROR]: Missing action in task request."

    key = str(action).strip().lower()

    def ok(**fields):
        return json.dumps({"ok": True, "action": key, **fields}, ensure_ascii=False, indent=2)

    if key in ("set", "set_list", "plan"):
        items = payload.get("tasks") or payload.get("items") or payload.get("titles")
        if items is None:
            return "[TASK ERROR]: 'set' requires a 'tasks' list."
        tasks = set_task_list(items if isinstance(items, list) else str(items))
        if not tasks:
            return "[TASK ERROR]: 'set' produced no usable tasks."
        return ok(count=len(tasks), state=format_task_state())

    if key in ("add", "append"):
        title = payload.get("title") or payload.get("task") or payload.get("text")
        task = add_task(title)
        if task is None:
            return "[TASK ERROR]: 'add' requires a non-empty 'title'."
        return ok(task=task, state=format_task_state())

    if key in ("done", "complete", "finish"):
        selector = payload.get("id") or payload.get("key") or payload.get("task") or payload.get("title")
        if selector is None:
            active = current_task()
            selector = active.get("id") if active else None
        task = mark_task_done(selector)
        if task is None:
            return f"[TASK ERROR]: No task matching '{selector}' to mark done."
        return ok(task=task, state=format_task_state())

    if key in ("fail", "block", "skip"):
        selector = payload.get("id") or payload.get("key") or payload.get("task")
        if selector is None:
            active = current_task()
            selector = active.get("id") if active else None
        status = "skipped" if key == "skip" else "failed"
        task = set_task_status(selector, status)
        if task is None:
            return f"[TASK ERROR]: No task matching '{selector}' to mark {status}."
        reason = payload.get("reason") or payload.get("text")
        if reason:
            add_task_note(selector, f"{status}: {reason}")
        return ok(task=task, state=format_task_state())

    if key in ("note", "record"):
        selector = payload.get("id") or payload.get("key") or payload.get("task")
        if selector is None:
            active = current_task()
            selector = active.get("id") if active else None
        task = add_task_note(selector, payload.get("text") or payload.get("note"))
        if task is None:
            return f"[TASK ERROR]: Could not attach a note to '{selector}'."
        return ok(task=task)

    if key in ("list", "state", "show"):
        return ok(state=format_task_state())

    if key in ("clear", "reset"):
        clear_tasks()
        return ok(state=format_task_state())

    return f"[TASK ERROR]: Unsupported task action '{action}'."
