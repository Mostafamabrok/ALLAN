import json
import os
import re

from llm_api import call_model
from parser import execute_actions, parse_actions
from user_interaction_space import sanitize_reply
from tasks import (
    TASKS_FILE,
    clear_tasks,
    current_task,
    format_task_state,
    get_pending_tasks,
    has_pending_tasks,
    list_tasks,
    mark_task_done,
    set_task_list,
)

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

INTERNAL VOCABULARY IS NEVER USER-FACING (all interfaces):
The task chain, step numbers and opcodes are machinery for running the work.
They are not things the user asked about, and on a spoken interface they are
unintelligible. In your reply, never say "task-1", "task 2", "step 3", "the task
chain", "memory search", "sticky note", "topical page", "opcode", or a
storage/ file path. Say what you did in the user's own terms instead: not
"I completed task 2 and wrote a sticky note", but "I saved that for later".
Report outcomes, not the bookkeeping you used to reach them.
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

# Agent loop limits. Overridable from Allan_Prime_Settings.json; these are the
# defaults so an existing settings file keeps working without edits.
#
# The step budget scales with the size of the chain ALLAN actually planned. A
# flat ceiling cut long jobs off mid-work while still being far more than a
# two-task job needs. Budget is recomputed each step, and grows if ALLAN adds
# tasks, so discovering more work mid-run extends the run instead of starving it.
BASE_STEP_BUDGET = int(SETTINGS.get("base_step_budget", 8))
STEPS_PER_TASK = int(SETTINGS.get("steps_per_task", 4))
MAX_STEPS_HARD_CAP = int(SETTINGS.get("max_steps_hard_cap", 40))
MAX_CONSECUTIVE_FAILURES = int(SETTINGS.get("max_consecutive_failures", 3))
MAX_EARLY_EXIT_NUDGES = int(SETTINGS.get("max_early_exit_nudges", 2))

# Back-compat: an existing settings file with max_iterations still pins the cap.
_LEGACY_MAX_ITERATIONS = SETTINGS.get("max_iterations")


def step_budget():
    """How many steps this run gets, given the work currently on the board.

    Derived from the TOTAL task count, not the pending count -- pending shrinks
    as tasks complete, which would shrink the budget out from under a run that
    is making good progress.
    """
    if _LEGACY_MAX_ITERATIONS:
        return int(_LEGACY_MAX_ITERATIONS)
    return min(MAX_STEPS_HARD_CAP, BASE_STEP_BUDGET + STEPS_PER_TASK * len(list_tasks()))


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


def handle_task_command(user_input):
    """Plain-text task commands typed by the user. ALLAN itself uses <task>."""
    text = str(user_input or "").strip()
    if not text:
        return None
    lower = text.lower()

    if lower in {"tasks", "list tasks", "show tasks", "task list", "todo list"}:
        return format_task_state() if list_tasks() else "There are no active tasks yet."

    if lower in {"clear tasks", "clear task list", "reset tasks", "wipe tasks"}:
        clear_tasks()
        return "Task list cleared."

    if lower in {"mark all tasks done", "complete all tasks", "finish all tasks"}:
        for task in list_tasks():
            mark_task_done(task.get("id"))
        return "All tasks marked as done."

    match = re.match(r"^(?:mark\s+)?(?:task|todo)\s+(.+?)\s+(?:done|complete|finished)$",
                     text, flags=re.IGNORECASE)
    if match:
        target = match.group(1).strip()
        task = mark_task_done(target)
        if task:
            return f"Marked task as done: {task.get('title')}"
        return f"I could not find the task '{target}' to mark done."

    if (re.match(r"^(set|create)\s+(task|todo)\s+list\s*[:\-]?\s*", text, flags=re.IGNORECASE)
            or "task list" in lower or "todo list" in lower
            or lower.startswith("tasks:") or lower.startswith("todo:")):
        tasks = set_task_list(text)
        if not tasks:
            return "I did not find any tasks to set."
        listing = "\n".join(f"{i + 1}. {t['title']}" for i, t in enumerate(tasks))
        return "Task list set:\n" + listing

    return None


def clear_history():
    _write_history(_empty_history())
    _remove_legacy_thread_files()


def _extract_user_reply(raw_response):
    match = re.search(r'<user_reply>(.*?)</user_reply>', raw_response or "", re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def build_stable_context():
    """The part of the prompt frozen for an entire run.

    This is cached block #1. Every model call in a run receives the identical
    string -- prompt caching is a byte-exact prefix match, so rebuilding it
    mid-run (after the run has appended to history) would cost every hit.

    Section order is load-bearing: history only grows by appending, so it goes
    LAST. That keeps each run's block a byte-exact extension of the previous
    one, which is what lets a later run read the entry an earlier one wrote.
    Put history first and every new entry shifts what follows, so the prefix
    diverges and every run pays a fresh cache write.

    Live task state is deliberately NOT in here -- it changes as the loop marks
    tasks done, so it is re-rendered per step in the volatile part instead.
    """
    return (
        LOOP_PROTOCOL + "\n\n"
        "STANDING CONTEXT (frozen for this run)\n\n"
        f"Sticky notes:\n{_format_sticky_notes_for_prompt()}\n\n"
        f"History:\n{_format_history_for_prompt(get_history())}"
    )


LOOP_PROTOCOL = """ALLAN AGENT LOOP PROTOCOL

You run in a loop. Each step you emit one action, the system executes it, and
you see the result on the next step. You keep going until the work is genuinely
finished, then you answer the user once. You are not answering the user on
every step -- most steps are work.

ACTIONS:

  <task>{"action": "set", "args": {"tasks": ["first", "second"]}}</task>
  <task>{"action": "done", "args": {"id": "task-1"}}</task>
  <task>{"action": "add", "args": {"title": "..."}}</task>
  <task>{"action": "note", "args": {"id": "task-1", "text": "what you found"}}</task>
  <task>{"action": "fail", "args": {"id": "task-1", "reason": "why it is blocked"}}</task>

  <tool>{"name": "web_search", "args": {"query": "...", "max_results": 3}}</tool>
  <tool>{"name": "web_dive", "args": {"url": "https://...", "max_chars": 2000}}</tool>

  <memory>{"action": "search", "args": {"query": "...", "scope": "all", "limit": 5}}</memory>
  <memory>{"action": "write", "args": {"kind": "sticky", "title": "...", "text": "..."}}</memory>
  <memory>{"action": "write", "args": {"kind": "topical", "page_name": "...", "content": "..."}}</memory>

  <ask_user>a specific question, when you need something only the user knows</ask_user>
  <user_reply>your single final answer to the user</user_reply>

KNOW WHAT YOU ARE TALKING ABOUT BEFORE YOU ACT:

The user refers to their own projects, people, notes, decisions and shorthand.
You are not expected to already know these. You ARE expected to find out instead
of guessing.

- If the request names something specific you have not already seen in this run
  -- a project, page, person, tool, deadline, or piece of shorthand -- your FIRST
  action is <memory> search for it. Do not plan around a guess about what it
  means.
- If memory does not have it, and you cannot do the work correctly without it,
  use <ask_user> and ask one specific question. Asking is cheap. Doing three
  steps of confident work on a wrong assumption is not.
- Do not infer what the user "probably meant" and proceed. Do not invent a
  plausible-sounding definition, plan or fact to fill a gap.
- If you are genuinely unsure whether the request means A or B, and they lead to
  different work, ask. Do not pick one silently.
- When you do answer, say what you actually found. If something is uncertain,
  partial, or came from an assumption, say so in the answer.

HOW TO RUN THE LOOP:

1. If the request needs more than one step, your FIRST action is
   <task>{"action": "set", ...}</task> laying out the steps. Do not announce the
   plan to the user -- just set it and start working. If orientation is needed,
   make "find out what X refers to" the first task.
2. If the request is a simple direct answer needing no tool, no memory lookup
   and no multi-step work, emit <user_reply> immediately. Do not invent tasks
   for trivial requests.
3. Otherwise work the CURRENT OBJECTIVE shown in the task chain.
4. When a task is genuinely complete, mark it done and move to the next. Record
   anything worth keeping with a task note or a memory write before moving on --
   your step-by-step observations are not permanent.
5. Only emit <user_reply> when every task is finished or you are truly blocked.
   <user_reply> ENDS THE RUN. Anything you have not done yet will not get done.

USE YOUR STEPS WELL -- you have a limited number per run:

- Combine the work with its bookkeeping in ONE step. Put the WORK FIRST and the
  task update after it:

      <memory>{"action": "write", "args": {...}}</memory>
      <task>{"action": "done", "args": {"id": "task-2"}}</task>

  Order matters. A step stops at its first failure, so if the write fails the
  task is NOT marked done -- which is correct. Put the task update first and you
  would be recording success for work that never happened.
  Spending a whole step on a lone <task>{"action":"done"} is a wasted step.
- Write ONE JSON object per block, and count your closing braces. A nested
  "args" object needs two at the end, not three. A malformed block does not run.
- Emit at most ONE tool or memory call per step -- you need to see its result
  before deciding the next one. Task updates alongside it are free.
- Do not create tasks for trivia. Three real tasks beat ten micro-tasks.
- If you are running low on steps, stop starting new work. Record what you have
  with a memory write or task note, then answer.

HARD RULES:
- At most one <tool> or <memory> per step. Never mix any action with
  <user_reply> or <ask_user> -- those two end the run.
- Never claim a tool or memory action succeeded. You will see the actual result
  on the next step; report only what it actually said.
- If an action fails, read the error and change approach. Do not repeat the same
  failing call.
- Memory is <memory>, never <tool> with name "memory". Tasks are <task>, never
  <tool> with name "task".
- Put no tool tags, memory tags, task tags or internal reasoning inside
  <user_reply> or <ask_user>. Those are the only things the user ever sees."""


def _extract_ask_user(raw_response):
    match = re.search(r'<ask_user>(.*?)</ask_user>', raw_response or "", re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def _build_step_prompt(user_input, step, budget, interface_name):
    """The volatile per-step suffix. Never cached -- it changes every step."""
    remaining = budget - step
    if remaining <= 0:
        pressure = ("THIS IS YOUR LAST STEP. Do not start anything new. Save anything "
                    "worth keeping, then answer the user with what you have.")
    elif remaining <= 2:
        pressure = (f"ONLY {remaining} STEPS LEFT AFTER THIS ONE. Stop starting new work. "
                    "Record what you have found, then answer.")
    elif remaining <= 4:
        pressure = f"{remaining} steps left after this one. Start converging."
    else:
        pressure = f"{remaining} steps left after this one."

    return (
        f"STEP {step} of {budget}. {pressure}\n\n"
        f"{format_task_state()}\n\n"
        f"ORIGINAL USER REQUEST: {user_input}\n\n"
        f"{get_interface_prompt(interface_name)}\n"
        "Emit your action now."
    )


def _format_observation(step, records):
    """Render executed actions into an observation block for the next step."""
    lines = [f"OBSERVATION FROM STEP {step}:"]
    for record in records:
        status = "OK" if record["ok"] else "FAILED"
        result = str(record["result"])
        if len(result) > 4000:
            result = result[:4000] + "\n...[truncated]"
        lines.append(f"[{status}] {record['label']}\n{result}")
    return "\n".join(lines)


def _call_step(prompt, blocks, interface_name):
    return call_model(
        prompt=prompt,
        model_name=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system_prompt=SYSTEM_PROMPT + "\n" + get_interface_prompt(interface_name),
        cached_context=blocks,
    )


def _force_final_answer(user_input, blocks, interface_name, reason):
    """Last call of a run that ran out of road. Ask for the answer, nothing else.

    The task chain is deliberately left intact: pending tasks persist to the next
    turn, so the user can say "continue" and the loop picks up where it stopped
    rather than starting over.
    """
    unfinished = get_pending_tasks()
    handoff = ""
    if unfinished:
        titles = "; ".join(str(t.get("title")) for t in unfinished[:5])
        handoff = (
            f"\n{len(unfinished)} task(s) are still unfinished: {titles}\n"
            "Report what you actually completed, then say plainly what is left. "
            "Tell the user the task list is saved and they can say 'continue' to "
            "pick up from here. Do not pretend the job is finished.\n"
        )

    prompt = (
        "The work loop has stopped early.\n"
        f"Reason: {reason}\n"
        f"{handoff}\n"
        f"ORIGINAL USER REQUEST: {user_input}\n\n"
        f"{format_task_state()}\n\n"
        f"{get_interface_prompt(interface_name)}\n"
        "Write the final user-facing answer now using only what the steps above "
        "actually established. Do not claim anything you did not verify. "
        "Emit only <user_reply>...</user_reply>."
    )
    _, response = _call_step(prompt, blocks, interface_name)
    if not response:
        return None
    append_to_internal_chat(f"ALLAN_FORCED_FINAL: {response}")

    reply = _extract_user_reply(response)
    if reply:
        return reply
    # No <user_reply>. Fall back to the bare text only if it is actually prose --
    # if the model emitted more action blocks, stripping the tags would print raw
    # JSON at the user. Better to say plainly that the run did not finish.
    if parse_actions(response):
        return None
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", response)).strip()
    return cleaned or None


def ALLAN_prime(user_input, interface_name="terminal", on_progress=None):
    """Run the agent loop until the work is done, then return one answer.

    Each iteration is one model call that emits one action. Actions are executed
    and fed back as observations. The run ends when ALLAN emits <user_reply>
    with no pending tasks, or when a guard trips.
    """
    def progress(event_type, **fields):
        """Emit a structured progress event.

        The engine never formats for humans -- it reports what happened and lets
        user_interaction_space decide what each interface shows. A terminal wants
        the mechanical detail; a voice interface must not read task ids aloud.
        """
        if on_progress:
            try:
                on_progress({"type": event_type, **fields})
            except Exception:
                pass  # a broken renderer must not kill a working run

    if isinstance(user_input, str) and user_input.strip().lower() == "full clear":
        return _full_clear()

    append_to_user_chat(f"User: {user_input}")

    # Direct task commands typed by the user are handled without a model call.
    task_command_result = handle_task_command(user_input)
    if task_command_result is not None:
        append_to_internal_chat(f"[TASK SYSTEM]: {task_command_result}")
        append_to_user_chat(f"ALLAN: {task_command_result}")
        return task_command_result

    stable_context = build_stable_context()
    observations = []          # append-only; each entry becomes its own cached block
    consecutive_failures = 0
    nudges = 0
    final_reply = None
    stop_reason = None

    step = 0
    while True:
        budget = step_budget()
        if step >= budget:
            stop_reason = f"the step budget of {budget} was used up"
            break
        step += 1

        objective = current_task()
        progress("step_started", step=step, budget=budget, remaining=budget - step,
                 objective=objective.get("title") if objective else None)

        blocks = [stable_context] + observations
        prompt = _build_step_prompt(user_input, step, budget, interface_name)

        thinking, response = _call_step(prompt, blocks, interface_name)
        if thinking:
            append_to_internal_chat(f"[ALLAN INTERNAL THOUGHT]: {thinking}")
        if response is None:
            stop_reason = "the model API stopped responding"
            break
        append_to_internal_chat(f"ALLAN_STEP_{step}: {response}")

        actions = parse_actions(response)
        reply = _extract_user_reply(response)

        # A question for the user ends the run immediately and is never nudged --
        # it is not a claim of completion, it is ALLAN admitting it needs input.
        # Pending tasks stay pending so the answer can resume the chain.
        question = _extract_ask_user(response)
        if question and not actions:
            progress("needs_input", step=step, question=question)
            append_to_user_chat(f"ALLAN: {question}")
            return sanitize_reply(question, interface_name)

        # An action always wins over a reply in the same output: do the work
        # first, deliver later. This is what stops ALLAN answering mid-task.
        if actions:
            tasks_before = {t.get("id"): t.get("status") for t in list_tasks()}
            records = execute_actions(actions, agent_id="ALLAN_Prime")
            for record in records:
                progress("action", step=step, kind=record["kind"], label=record["label"],
                         ok=record["ok"], detail=str(record["result"])[:200])
                append_to_internal_chat(f"[EXECUTED {record['label']}]: {record['result']}")

            # Report task-state changes as their own events. Interfaces that do
            # not care about opcodes can still narrate real progress from these.
            after = list_tasks()
            if not tasks_before and after:
                progress("plan_set", count=len(after),
                         tasks=[t.get("title") for t in after])
            else:
                for task in after:
                    was, now = tasks_before.get(task.get("id")), task.get("status")
                    if was is not None and was != now and now == "done":
                        progress("task_done", step=step, id=task.get("id"),
                                 title=task.get("title"),
                                 remaining=len(get_pending_tasks()))

            observations.append(_format_observation(step, records))

            if all(not r["ok"] for r in records):
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    stop_reason = (f"{consecutive_failures} steps in a row failed, so the "
                                   "loop stopped instead of burning more tokens")
                    break
            else:
                consecutive_failures = 0
            continue

        if reply:
            # Finishing with work still outstanding is the exact failure mode
            # this loop exists to prevent -- push back, but only a few times.
            if has_pending_tasks() and nudges < MAX_EARLY_EXIT_NUDGES:
                nudges += 1
                pending = current_task()
                progress("rejected", step=step, reason="premature_finish",
                         detail="tried to finish with tasks pending, continuing")
                observations.append(
                    f"OBSERVATION FROM STEP {step}:\n"
                    "[REJECTED] You tried to end the run, but the task chain is not finished. "
                    f"The current objective is still: {pending.get('id')} -- {pending.get('title')}. "
                    "Either work it now, or mark it done/failed if it genuinely is. "
                    "Do not answer the user yet."
                )
                continue
            final_reply = reply
            stop_reason = "complete"
            break

        # Neither an action nor a reply: malformed step.
        consecutive_failures += 1
        progress("rejected", step=step, reason="invalid_output",
                 detail="no valid action in output")
        observations.append(
            f"OBSERVATION FROM STEP {step}:\n"
            "[REJECTED] Your output contained no valid action block. Emit <task>, "
            "<tool> or <memory> with valid JSON inside, or <ask_user> to ask the "
            "user something, or <user_reply> to finish."
        )
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            stop_reason = "the model stopped producing valid actions"
            break

    if final_reply is None:
        progress("wrapping_up", reason=stop_reason)
        final_reply = _force_final_answer(
            user_input, [stable_context] + observations, interface_name, stop_reason
        )
    if final_reply is None:
        final_reply = f"I stopped before finishing: {stop_reason}."

    progress("run_finished", steps=step,
             outcome="complete" if stop_reason == "complete" else "stopped",
             reason=None if stop_reason == "complete" else stop_reason)

    append_to_user_chat(f"ALLAN: {final_reply}")
    return sanitize_reply(final_reply, interface_name)


def _full_clear():
    """Wipe raw context, memory and tasks. Explicit user request only."""
    try:
        for directory in (RAW_CONTEXT_DIR, MEMORY_DIR):
            if os.path.exists(directory):
                for name in os.listdir(directory):
                    path = os.path.join(directory, name)
                    if os.path.isfile(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
        if os.path.exists(TASKS_FILE):
            try:
                os.remove(TASKS_FILE)
            except Exception:
                pass
        _write_history(_empty_history())
        with open(GENERAL_SUMMARY_FILE, "w", encoding="utf-8") as f:
            json.dump({"summaries": []}, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception:
        pass
    return "All memory cleared. (raw histories and summaries wiped)"
