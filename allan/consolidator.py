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
            "Event qualification: Create a new summary item only when an entry (or small group of consecutive entries) describes a distinct action or change in state: e.g., a tool invocation, an external data fetch result, a decision, a plan step, or a user question that requires work. Do NOT create separate events for simple user echoes, confirmations, or repeated user_reply mirrors.\n",
            "Requirements:\n- For each summary item, provide: 'summary' (one or two sentences), 'compact' (a single extremely short phrase <= 12 words), 'references' (list of raw entry ids from the input), and 'agent' (the agent filename).\n",
            "- The 'compact' field should be highly compressed (focus keywords or 6-12 words) to save tokens for later retrieval.\n",
            "- Return the result as a JSON array of objects with these fields. IMPORTANT: Return ONLY valid JSON (a JSON array). Do NOT include the raw entry texts in the output. If you cannot produce valid JSON, return an empty JSON array '[]'.\n\n",
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

        # If parsing failed or yielded no references, attempt a strict JSON-only retry using the raw entries.
        if not parsed or all(not it.get("references") for it in parsed):
            combined_refs = [{"agent": agent_name, "id": int(e.get('id'))} for e in new_entries]
            # strict retry: ask the model to return only valid JSON array, otherwise return []
            strict_prompt = (
                "Return ONLY a JSON array of summary objects following the earlier requirements.\nDo not include raw texts.\nInput entries:\n" + "\n".join([f"ID:{e.get('id')} TS:{e.get('timestamp')} TEXT:{e.get('text','')}" for e in new_entries])
            )
            try:
                thinking_retry, response_retry = call_model(
                    prompt=strict_prompt,
                    model_name=MODEL_NAME,
                    max_tokens=MAX_TOKENS,
                    system_prompt=SETTINGS.get("system_prompt", ""),
                )
                jstart_r = response_retry.find("[")
                jend_r = response_retry.rfind("]")
                if jstart_r != -1 and jend_r != -1 and jend_r > jstart_r:
                    try:
                        parsed = json.loads(response_retry[jstart_r:jend_r+1])
                        # normalize references below as usual
                    except Exception:
                        parsed = []
                else:
                    parsed = []
            except Exception:
                parsed = []

            # if still nothing parseable, create a compact heuristic summary (do NOT dump full raw texts)
            if not parsed:
                # Create a short merge summary: count + brief tags from entry starts
                count = len(new_entries)
                starts = [ (e.get('text','')[:80].replace('\n',' ') ) for e in new_entries ]
                summary_text = f"{count} events: " + " ; ".join(starts[:3])
                compact_text = ", ".join([s.split()[:6] and " ".join(s.split()[:6]) for s in starts[:3]])
                parsed = [{"summary": summary_text, "compact": compact_text, "references": combined_refs, "agent": agent_name}]

        # Append parsed summaries to general summary file, assign incremental ids
        next_sum_id = 1
        if summaries:
            try:
                next_sum_id = max(int(s.get("id", 0)) for s in summaries) + 1
            except Exception:
                next_sum_id = len(summaries) + 1

        for item in parsed:
            item_id = next_sum_id
            summary_text = item.get("summary") or item.get("text") or ""
            compact_text = item.get("compact")

            # If the model returned a tool tag, placeholder, or an extremely short/empty summary,
            # try to resolve the referenced raw entries and ask the LLM to produce a proper compact summary.
            need_resolution = False
            try:
                if not summary_text.strip():
                    need_resolution = True
                elif "<tool>" in summary_text.lower():
                    need_resolution = True
                elif len(summary_text.strip()) < 30:
                    need_resolution = True
            except Exception:
                need_resolution = True

            if need_resolution:
                refs = item.get("references", [])
                collected_texts = []
                for r in refs:
                    try:
                        agent_file = os.path.join(RAW_CONTEXT_DIR, r.get("agent"))
                        data = _load_json(agent_file, {"entries": []})
                        for e in data.get("entries", []):
                            try:
                                if int(e.get("id", 0)) == int(r.get("id", 0)):
                                    collected_texts.append(e.get("text", ""))
                            except Exception:
                                pass
                    except Exception:
                        pass
                combined = "\n\n".join(collected_texts).strip()
                if combined:
                    # Ask the model to compress the combined raw texts into a short summary + compact phrase
                    comp_prompt = (
                        "Compress the following raw agent texts into a single JSON object with fields: '")
                    comp_prompt += ("summary' (1-2 sentences) and 'compact' (a single highly compressed phrase, 6-12 words).\\n\\nRaw texts:\n" + combined)
                    try:
                        thinking2, response2 = call_model(
                            prompt=comp_prompt,
                            model_name=MODEL_NAME,
                            max_tokens=min(400, MAX_TOKENS),
                            system_prompt=SETTINGS.get("system_prompt", ""),
                        )
                        # Extract JSON object from response
                        jstart = response2.find("{")
                        jend = response2.rfind("}")
                        if jstart != -1 and jend != -1 and jend > jstart:
                            try:
                                parsed2 = json.loads(response2[jstart:jend+1])
                                summary_text = parsed2.get("summary", summary_text)
                                compact_text = parsed2.get("compact", compact_text)
                            except Exception:
                                # fallback heuristics
                                summary_text = " ".join(combined.split()[:60])
                                compact_text = " ".join(combined.split()[:10])
                        else:
                            summary_text = " ".join(combined.split()[:60])
                            compact_text = " ".join(combined.split()[:10])
                    except Exception:
                        summary_text = " ".join(combined.split()[:60])
                        compact_text = " ".join(combined.split()[:10])

            # fallback compact: take first 10 words if still missing
            if not compact_text or not str(compact_text).strip():
                compact_text = " ".join(summary_text.split()[:10]).strip()

            item_entry = {
                "id": item_id,
                "agent": agent_name,
                "summary": summary_text,
                "compact_summary": compact_text,
                "references": item.get("references", []),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            summaries.append(item_entry)
            next_sum_id += 1

    # Post-process existing summaries: for any summary that looks like a tool-tag placeholder or is too short,
    # attempt to regenerate a compact summary by resolving its references and compressing the raw texts.
    def _regenerate_from_refs(entry):
        try:
            stext = entry.get("summary","") or ""
            if stext and "<tool>" not in stext.lower() and len(stext.strip()) >= 30:
                return entry
            refs = entry.get("references", [])
            collected = []
            for r in refs:
                try:
                    af = os.path.join(RAW_CONTEXT_DIR, r.get("agent"))
                    data = _load_json(af, {"entries": []})
                    for e in data.get("entries", []):
                        try:
                            if int(e.get("id", 0)) == int(r.get("id", 0)):
                                collected.append(e.get("text", ""))
                        except Exception:
                            pass
                except Exception:
                    pass
            combined = "\n\n".join(collected).strip()
            if not combined:
                return entry
            comp_prompt = (
                "Compress the following raw agent texts into a single JSON object with fields: 'summary' (1-2 sentences) and 'compact' (a single highly compressed phrase, 6-12 words).\\n\\nRaw texts:\n" + combined)
            thinking3, response3 = call_model(
                prompt=comp_prompt,
                model_name=MODEL_NAME,
                max_tokens=min(400, MAX_TOKENS),
                system_prompt=SETTINGS.get("system_prompt", ""),
            )
            jstart = response3.find("{")
            jend = response3.rfind("}")
            if jstart != -1 and jend != -1 and jend > jstart:
                try:
                    parsed3 = json.loads(response3[jstart:jend+1])
                    entry["summary"] = parsed3.get("summary", entry.get("summary",""))
                    entry["compact_summary"] = parsed3.get("compact", entry.get("compact_summary",""))
                except Exception:
                    entry["summary"] = " ".join(combined.split()[:60])
                    entry["compact_summary"] = " ".join(combined.split()[:10])
            else:
                entry["summary"] = " ".join(combined.split()[:60])
                entry["compact_summary"] = " ".join(combined.split()[:10])
            return entry
        except Exception:
            return entry

    for idx, s in enumerate(summaries):
        try:
            stext = s.get("summary","") or ""
            if (not stext.strip()) or ("<tool>" in stext.lower()) or len(stext.strip()) < 30:
                summaries[idx] = _regenerate_from_refs(s)
        except Exception:
            pass

    # write back
    _write_json(GENERAL_SUMMARY_FILE, {"summaries": summaries})


if __name__ == "__main__":
    compress_events()
