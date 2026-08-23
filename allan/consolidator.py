import os
import json
from glob import glob
from datetime import datetime, timezone

from llm_api import call_model

# Load settings if present
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "Allan_Prime_Settings.json")
SETTINGS = {}
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as sf:
            SETTINGS = json.load(sf)
    except Exception:
        SETTINGS = {}

MODEL_NAME = SETTINGS.get("model_name")
MAX_TOKENS = SETTINGS.get("max_tokens")

STORAGE_DIR = os.path.join(BASE_DIR, "storage")
RAW_CONTEXT_DIR = os.path.join(STORAGE_DIR, "raw_agent_context")
MEMORY_DIR = os.path.join(STORAGE_DIR, "memory")
GENERAL_SUMMARY_FILE = os.path.join(MEMORY_DIR, "general_summarized_event_list.json")


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _get_last_summarized_id_for_agent(agent_name, summaries):
    """Return the maximum raw entry id for the given agent that has already been referenced in summaries.

    References in summaries are normalized to objects: {"agent": "agent1.json", "id": 2}.
    Legacy formats (strings like "agent1.json:2" or "2") are also supported.
    """
    max_ref = 0
    for s in summaries:
        refs = s.get("references", [])
        for r in refs:
            try:
                if isinstance(r, dict):
                    if r.get("agent") == agent_name:
                        rid = int(r.get("id", 0))
                        if rid > max_ref:
                            max_ref = rid
                elif isinstance(r, str):
                    if ":" in r:
                        parts = r.split(":", 1)
                        a, rid_s = parts[0], parts[1]
                        if a == agent_name:
                            rid = int(rid_s)
                            if rid > max_ref:
                                max_ref = rid
                    else:
                        # plain id string: only consider if summary.agent matches
                        if s.get("agent") == agent_name:
                            rid = int(r)
                            if rid > max_ref:
                                max_ref = rid
                elif isinstance(r, int):
                    if s.get("agent") == agent_name:
                        rid = int(r)
                        if rid > max_ref:
                            max_ref = rid
            except Exception:
                pass
    return max_ref


def _collect_new_entries(agent_file, last_id):
    data = _load_json(agent_file, {"entries": []})
    entries = data.get("entries", [])
    new = [e for e in entries if int(e.get("id", 0)) > last_id]
    return new


def compress_events():
    """Scan raw_agent_context/*.json and consolidate new events using the LLM.

    Produces/updates memory/general_summarized_event_list.json with summarized items referencing raw ids.
    """
    if not MODEL_NAME or not MAX_TOKENS:
        raise RuntimeError("Missing model settings in Allan_Prime_Settings.json")

    if not os.path.exists(RAW_CONTEXT_DIR):
        return
    if not os.path.exists(MEMORY_DIR):
        os.makedirs(MEMORY_DIR)

    summaries_data = _load_json(GENERAL_SUMMARY_FILE, {"summaries": []})
    summaries = summaries_data.setdefault("summaries", [])

    # Normalize existing summary references to structured objects: {"agent": "agent.json", "id": N}
    for s in summaries:
        agent_of_summary = s.get("agent") or "unknown"
        refs = s.get("references", [])
        norm_refs = []
        for r in refs:
            try:
                if isinstance(r, dict):
                    # already structured
                    norm_refs.append({"agent": r.get("agent", agent_of_summary), "id": int(r.get("id", 0))})
                elif isinstance(r, str):
                    if ":" in r:
                        a, rid = r.split(":", 1)
                        norm_refs.append({"agent": a, "id": int(rid)})
                    else:
                        norm_refs.append({"agent": agent_of_summary, "id": int(r)})
                elif isinstance(r, int):
                    norm_refs.append({"agent": agent_of_summary, "id": int(r)})
            except Exception:
                pass
        s["references"] = norm_refs

    agent_files = glob(os.path.join(RAW_CONTEXT_DIR, "*.json"))
    for af in agent_files:
        agent_name = os.path.basename(af)
        last_id = _get_last_summarized_id_for_agent(agent_name, summaries)
        new_entries = _collect_new_entries(af, last_id)
        if not new_entries:
            continue

        # Build a prompt for the model summarization
        prompt_parts = [
            "You are given a sequence of raw agent history entries. Produce a compact list of concise summary items.\n",
            "Requirements:\n- For each summary item, provide: 'summary' (one or two sentences), 'references' (list of raw entry ids from the input), and 'agent' (the agent filename).\n",
            "- Return the result as a JSON array of objects. Do NOT include the raw entry texts in the output.\n\n",
            "Input entries:\n",
        ]
        for e in new_entries:
            eid = e.get("id")
            ts = e.get("timestamp")
            txt = e.get("text", "")
            prompt_parts.append(f"ID:{eid} TS:{ts} TEXT:{txt}\n")

        prompt = "".join(prompt_parts)

        thinking, response = call_model(
            prompt=prompt,
            model_name=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            system_prompt=SETTINGS.get("system_prompt", ""),
        )

        # Prefer response text
        raw_response = response or ""

        # Try to extract JSON from the model output
        json_start = raw_response.find("[")
        json_end = raw_response.rfind("]")
        parsed = []
        if json_start != -1 and json_end != -1 and json_end > json_start:
            try:
                parsed = json.loads(raw_response[json_start:json_end+1])
            except Exception:
                parsed = []

        # Normalize parsed references to structured objects: {"agent":"agent.json", "id": N}
        normalized = []
        for item in parsed:
            refs = item.get("references", [])
            norm_refs = []
            for r in refs:
                try:
                    if isinstance(r, dict):
                        # already structured
                        norm_refs.append({"agent": r.get("agent", agent_name), "id": int(r.get("id", 0))})
                    elif isinstance(r, int):
                        norm_refs.append({"agent": agent_name, "id": int(r)})
                    elif isinstance(r, str):
                        if ":" in r:
                            a, rid = r.split(":", 1)
                            norm_refs.append({"agent": a, "id": int(rid)})
                        else:
                            norm_refs.append({"agent": agent_name, "id": int(r)})
                except Exception:
                    pass
            item["references"] = norm_refs
            item["agent"] = agent_name
            normalized.append(item)
        parsed = normalized

        # If parsing failed or yielded no references, treat whole response as a single summary
        if not parsed or all(not it.get("references") for it in parsed):
            combined_refs = [{"agent": agent_name, "id": int(e.get('id'))} for e in new_entries]
            parsed = [{"summary": raw_response.strip(), "references": combined_refs, "agent": agent_name}]

        # Append parsed summaries to general summary file, assign incremental ids
        next_sum_id = 1
        if summaries:
            try:
                next_sum_id = max(int(s.get("id", 0)) for s in summaries) + 1
            except Exception:
                next_sum_id = len(summaries) + 1

        for item in parsed:
            item_id = next_sum_id
            item_entry = {
                "id": item_id,
                "agent": agent_name,
                "summary": item.get("summary") or item.get("text") or "",
                "references": item.get("references", []),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            summaries.append(item_entry)
            next_sum_id += 1

    # write back
    _write_json(GENERAL_SUMMARY_FILE, {"summaries": summaries})


if __name__ == "__main__":
    compress_events()
