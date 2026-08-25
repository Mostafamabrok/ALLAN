import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
RAW_CONTEXT_DIR = STORAGE_DIR / "raw_agent_context"
MEMORY_DIR = STORAGE_DIR / "memory"
TOPICAL_DIR = MEMORY_DIR / "topical"
GENERAL_SUMMARY_FILE = MEMORY_DIR / "general_summarized_event_list.json"
STICKY_FILE = MEMORY_DIR / "sticky_notes.json"


def _ensure_layout():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    TOPICAL_DIR.mkdir(parents=True, exist_ok=True)

    if not GENERAL_SUMMARY_FILE.exists():
        with open(GENERAL_SUMMARY_FILE, "w", encoding="utf-8") as f:
            json.dump({"summaries": []}, f, ensure_ascii=False, indent=2)
            f.write("\n")

    if not STICKY_FILE.exists():
        with open(STICKY_FILE, "w", encoding="utf-8") as f:
            json.dump({"notes": []}, f, ensure_ascii=False, indent=2)
            f.write("\n")


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _slugify_name(name):
    text = str(name or "untitled").strip()
    is_markdown = text.lower().endswith(".md")
    text = re.sub(r"\.md$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z0-9 _-]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text or "untitled"
    return f"{text}.md" if is_markdown or not text.endswith(".md") else text


def _page_path(page_name):
    return TOPICAL_DIR / _slugify_name(page_name)


def _snippet_from_text(text, query=None, max_len=180):
    text = str(text or "").replace("\n", " ")
    if not text:
        return ""
    if query:
        q = str(query).lower()
        low = text.lower()
        idx = low.find(q)
        if idx != -1:
            start = max(0, idx - 60)
            end = min(len(text), idx + 120)
            snippet = text[start:end].strip()
            return snippet if len(snippet) < max_len else snippet[:max_len] + "..."
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _tokenize(text):
    return [t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t]


def _match_query(text, query):
    """True if the text contains the whole query or any single query term.

    Term-level matching matters: a search for "monthly budget rocket" should
    still surface the budget page even though that exact phrase appears nowhere.
    """
    if not query:
        return True
    blob = str(text or "").lower()
    if str(query).lower() in blob:
        return True
    terms = _tokenize(query)
    if not terms:
        return False
    blob_terms = set(_tokenize(blob))
    return any(term in blob_terms for term in terms)


# Small nudge applied after relevance, used only to break ties between items
# that matched the query equally well.
KIND_TIEBREAK = {"topical": 0.3, "sticky": 0.2, "summary": 0.1, "raw": 0.0}


def _blob_for(item):
    kind = str(item.get("kind") or "").lower()
    if kind == "topical":
        return " ".join([str(item.get("page") or ""), str(item.get("snippet") or "")])
    if kind == "summary":
        return " ".join([
            str(item.get("summary") or ""),
            str(item.get("compact_summary") or ""),
            str(item.get("agent") or ""),
            " ".join(str(r) for r in item.get("references", [])),
        ])
    if kind == "sticky":
        return " ".join([
            str(item.get("title") or ""),
            str(item.get("text") or ""),
            " ".join(str(tag) for tag in item.get("tags", [])),
        ])
    return " ".join([
        str(item.get("thread") or ""),
        str(item.get("text") or ""),
        str(item.get("snippet") or ""),
    ])


def _score_result(item, query):
    """Relevance first, memory tier only as a tiebreak.

    The old version sorted by tier before score, so any topical hit outranked
    an exact sticky-note match. Score now dominates.
    """
    q = str(query or "").strip().lower()
    if not q:
        return 0.0

    blob = _blob_for(item).lower()
    terms = _tokenize(q)
    blob_terms = set(_tokenize(blob))

    score = 0.0
    if q in blob:
        score += 10.0                                    # exact phrase
    if terms:
        hits = sum(1 for term in terms if term in blob_terms)
        if hits == len(terms):
            score += 5.0                                 # every term present
        score += 2.0 * (hits / len(terms))               # partial credit

    return score + KIND_TIEBREAK.get(str(item.get("kind") or "").lower(), 0.0)


def search_memory(query, scope="all", limit=10):
    _ensure_layout()
    q = str(query or "").strip()
    if not q:
        return {"query": q, "count": 0, "results": []}

    scope_key = str(scope or "all").lower()

    def _collect_topical_matches():
        matches = []
        for path in sorted(TOPICAL_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if _match_query(text, q) or _match_query(path.stem, q):
                matches.append({
                    "kind": "topical",
                    "page": path.name,
                    "path": str(path),
                    "snippet": _snippet_from_text(text, q),
                })
        return matches

    def _collect_summary_matches():
        matches = []
        summaries = _read_json(GENERAL_SUMMARY_FILE, {"summaries": []}).get("summaries", [])
        for item in summaries:
            haystack = " ".join([
                str(item.get("summary", "")),
                str(item.get("compact_summary", "")),
                " ".join(str(r) for r in item.get("references", [])),
            ])
            if _match_query(haystack, q):
                matches.append({
                    "kind": "summary",
                    "id": item.get("id"),
                    "agent": item.get("agent"),
                    "summary": item.get("summary", ""),
                    "compact_summary": item.get("compact_summary", ""),
                    "references": item.get("references", []),
                    "snippet": _snippet_from_text(item.get("summary", ""), q),
                })
        return matches

    def _collect_sticky_matches():
        matches = []
        sticky = _read_json(STICKY_FILE, {"notes": []}).get("notes", [])
        for note in sticky:
            haystack = " ".join([note.get("text", ""), " ".join(note.get("tags", []))])
            if _match_query(haystack, q):
                matches.append({
                    "kind": "sticky",
                    "id": note.get("id"),
                    "title": note.get("title") or "Sticky Note",
                    "text": note.get("text", ""),
                    "tags": note.get("tags", []),
                    "snippet": _snippet_from_text(note.get("text", ""), q),
                })
        return matches

    def _collect_raw_matches():
        matches = []
        for path in sorted(RAW_CONTEXT_DIR.glob("*.json")):
            payload = _read_json(path, {"entries": []})
            for entry in payload.get("entries", []):
                text = entry.get("text", "")
                if _match_query(text, q):
                    matches.append({
                        "kind": "raw",
                        "agent": path.name,
                        "id": entry.get("id"),
                        "thread": entry.get("thread"),
                        "timestamp": entry.get("timestamp"),
                        "snippet": _snippet_from_text(text, q),
                    })
        return matches

    def finalize(matches):
        ordered = []
        for item in matches:
            item_copy = dict(item)
            item_copy["_score"] = _score_result(item_copy, q)
            ordered.append(item_copy)
        # Relevance first. Tier is already folded into the score as a tiebreak.
        ordered.sort(key=lambda item: -item.get("_score", 0))

        deduped = []
        seen = set()
        for item in ordered:
            item.pop("_score", None)
            marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if marker not in seen:
                deduped.append(item)
                seen.add(marker)
        return deduped

    # Every tier whose alias set contains the requested scope gets searched.
    # "all" means all of them -- it used to mean "the first tier that hits",
    # so one weak topical match could hide every sticky note and summary.
    collectors = (
        (("all", "topical", "pages", "notes"), _collect_topical_matches),
        (("all", "summary", "summaries", "general_summary", "gsumel"), _collect_summary_matches),
        (("all", "sticky", "sticky_notes"), _collect_sticky_matches),
        (("all", "raw", "agent", "context"), _collect_raw_matches),
    )

    matches = []
    scopes_searched = []
    for aliases, collect in collectors:
        if scope_key in aliases:
            scopes_searched.append(aliases[1])
            try:
                matches.extend(collect())
            except Exception:
                pass

    if not scopes_searched:
        return {
            "query": q,
            "scope": scope_key,
            "error": f"Unknown scope '{scope_key}'. Use one of: topical, summary, sticky, raw, all.",
            "count": 0,
            "results": [],
        }

    ranked = finalize(matches)
    total = len(ranked)
    if limit is not None:
        ranked = ranked[: int(limit)]

    return {
        "query": q,
        "scopes_searched": scopes_searched,
        "count": len(ranked),
        "total_matches": total,
        "truncated": total > len(ranked),
        "results": ranked,
    }


def self_priority(kind):
    priorities = {
        "topical": 0,
        "summary": 1,
        "sticky": 2,
        "raw": 3,
    }
    return priorities.get(str(kind).lower(), 99)


def retrieve_memory(kind="all", key=None, limit=20):
    _ensure_layout()
    kind_key = str(kind or "all").lower()

    if kind_key in ("all", "everything"):
        return {
            "sticky": _read_json(STICKY_FILE, {"notes": []}).get("notes", []),
            "summaries": _read_json(GENERAL_SUMMARY_FILE, {"summaries": []}).get("summaries", []),
            "topical_pages": [p.name for p in sorted(TOPICAL_DIR.glob("*.md"))],
            "raw_agents": [p.name for p in sorted(RAW_CONTEXT_DIR.glob("*.json"))],
        }

    if kind_key in ("sticky", "sticky_notes"):
        sticky = _read_json(STICKY_FILE, {"notes": []}).get("notes", [])
        if key is not None:
            for note in sticky:
                if str(note.get("id")) == str(key):
                    return note
            return None
        if limit is not None:
            return sticky[: int(limit)]
        return sticky

    if kind_key in ("summary", "summaries", "general_summary", "gsumel"):
        summaries = _read_json(GENERAL_SUMMARY_FILE, {"summaries": []}).get("summaries", [])
        if key is not None:
            for item in summaries:
                if str(item.get("id")) == str(key):
                    return item
            return None
        if limit is not None:
            return summaries[: int(limit)]
        return summaries

    if kind_key in ("topical", "page", "pages"):
        if key is None:
            return [p.name for p in sorted(TOPICAL_DIR.glob("*.md"))]
        page_file = _page_path(key)
        if not page_file.exists():
            return None
        return page_file.read_text(encoding="utf-8", errors="ignore")

    if kind_key in ("raw", "context", "agent"):
        if key is None:
            return [p.name for p in sorted(RAW_CONTEXT_DIR.glob("*.json"))]
        file_path = RAW_CONTEXT_DIR / str(key)
        if not file_path.exists():
            return None
        return _read_json(file_path, {"entries": []})

    return None


def write_memory(kind, payload, *, title=None, page_name=None, tags=None):
    _ensure_layout()
    kind_key = str(kind or "").lower()

    if kind_key in ("sticky", "sticky_notes"):
        if isinstance(payload, dict):
            text = payload.get("text") or payload.get("content") or ""
            note_title = payload.get("title") or title or "Sticky Note"
            note_tags = payload.get("tags") or tags or []
        else:
            text = str(payload)
            note_title = title or "Sticky Note"
            note_tags = tags or []
        sticky = _read_json(STICKY_FILE, {"notes": []})
        notes = sticky.setdefault("notes", [])
        next_id = 1
        if notes:
            next_id = max(int(n.get("id", 0)) for n in notes) + 1
        note = {
            "id": next_id,
            "title": note_title,
            "text": text,
            "tags": list(note_tags),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        notes.append(note)
        _write_json(STICKY_FILE, sticky)
        return note

    if kind_key in ("summary", "summaries", "general_summary", "gsumel"):
        if isinstance(payload, dict):
            item = payload.copy()
        else:
            item = {"summary": str(payload), "compact_summary": str(payload)[:120], "references": []}
        summary = _read_json(GENERAL_SUMMARY_FILE, {"summaries": []})
        summaries = summary.setdefault("summaries", [])
        next_id = 1
        if summaries:
            next_id = max(int(s.get("id", 0)) for s in summaries) + 1
        item.setdefault("id", next_id)
        item.setdefault("agent", "memory.py")
        item.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        summaries.append(item)
        _write_json(GENERAL_SUMMARY_FILE, summary)
        return item

    if kind_key in ("topical", "page", "pages"):
        page_name = page_name or title or "untitled"
        page_file = _page_path(page_name)
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        page_file.write_text(content, encoding="utf-8")
        return {"page": page_file.name, "path": str(page_file), "content": content}

    return {"error": f"Unsupported memory kind: {kind}"}


def _note_matches_key(note, key):
    if key is None:
        return False
    s = str(key).strip()
    if not s:
        return False
    if str(note.get("id")) == s:
        return True
    if str(note.get("title") or "").strip() == s:
        return True
    if str(note.get("text") or "").strip() == s:
        return True
    return False


def rewrite_memory(kind, key, payload, *, page_name=None, tags=None):
    _ensure_layout()
    kind_key = str(kind or "").lower()

    if kind_key in ("sticky", "sticky_notes"):
        sticky = _read_json(STICKY_FILE, {"notes": []})
        notes = sticky.get("notes", [])
        for index, note in enumerate(notes):
            if _note_matches_key(note, key):
                if isinstance(payload, dict):
                    note["text"] = payload.get("text") or payload.get("content") or note.get("text", "")
                    if payload.get("title"):
                        note["title"] = payload["title"]
                    if payload.get("tags") or tags:
                        note["tags"] = list(payload.get("tags") or tags or note.get("tags", []))
                else:
                    note["text"] = str(payload)
                note["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_json(STICKY_FILE, sticky)
                return note
        return {"error": f"Sticky note {key} not found"}

    if kind_key in ("topical", "page", "pages"):
        page_path = _page_path(key if page_name is None else page_name)
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        page_path.write_text(content, encoding="utf-8")
        return {"page": page_path.name, "path": str(page_path), "content": content}

    if kind_key in ("summary", "summaries", "general_summary", "gsumel"):
        summary = _read_json(GENERAL_SUMMARY_FILE, {"summaries": []})
        summaries = summary.get("summaries", [])
        for index, item in enumerate(summaries):
            if str(item.get("id")) == str(key):
                if isinstance(payload, dict):
                    summaries[index].update(payload)
                else:
                    summaries[index]["summary"] = str(payload)
                _write_json(GENERAL_SUMMARY_FILE, summary)
                return summaries[index]
        return {"error": f"Summary {key} not found"}

    return {"error": f"Unsupported memory kind: {kind}"}


def delete_memory(kind, key):
    _ensure_layout()
    kind_key = str(kind or "").lower()

    if kind_key in ("sticky", "sticky_notes"):
        sticky = _read_json(STICKY_FILE, {"notes": []})
        notes = sticky.get("notes", [])
        matched = False
        new_notes = []
        for note in notes:
            if _note_matches_key(note, key):
                matched = True
                continue
            new_notes.append(note)

        if not matched:
            return {"deleted": False, "kind": "sticky", "id": key, "reason": "not_found"}

        sticky["notes"] = new_notes
        _write_json(STICKY_FILE, sticky)
        return {"deleted": True, "kind": "sticky", "id": key}

    if kind_key in ("topical", "page", "pages"):
        page_path = _page_path(key)
        if page_path.exists():
            page_path.unlink()
            return {"deleted": True, "kind": "topical", "page": page_path.name}
        return {"error": f"Page {key} not found"}

    if kind_key in ("summary", "summaries", "general_summary", "gsumel"):
        summary = _read_json(GENERAL_SUMMARY_FILE, {"summaries": []})
        summaries = summary.get("summaries", [])
        filtered = [item for item in summaries if str(item.get("id")) != str(key)]
        summary["summaries"] = filtered
        _write_json(GENERAL_SUMMARY_FILE, summary)
        return {"deleted": True, "kind": "summary", "id": key}

    return {"error": f"Unsupported memory kind: {kind}"}


def retrieve_all_memory():
    return retrieve_memory(kind="all")


def call_memory(request, agent_id="ALLAN_Prime"):
    if isinstance(request, str):
        try:
            request = json.loads(request)
        except Exception:
            return "[MEMORY ERROR]: Invalid memory request JSON."

    if not isinstance(request, dict):
        return "[MEMORY ERROR]: Memory request must be a JSON object."

    # Legacy/wrong format: memory wrapped in a tool tag is invalid.
    # Reject it explicitly so the caller knows the memory call failed instead of pretending success.
    if request.get("name") == "memory":
        return "[MEMORY ERROR]: Invalid memory call format. Memory operations must use <memory>...</memory> and never be wrapped in <tool>."

    # Accept both shapes:
    #   {"action": "search", "args": { ... }}
    #   {"action": "search", "query": "..."}
    action = request.get("action") or request.get("name") or request.get("type")
    payload = request.get("args") if isinstance(request.get("args"), dict) else request
    if action is None:
        return "[MEMORY ERROR]: Missing action/name in memory request."

    action_key = str(action).lower()

    if action_key in ("search_memory", "search", "find"):
        query = payload.get("query") or payload.get("text") or payload.get("page") or ""
        scope = payload.get("scope", "all")
        limit = payload.get("limit", 10)
        return json.dumps(search_memory(query, scope=scope, limit=limit), ensure_ascii=False, indent=2)

    if action_key in ("retrieve_memory", "retrieve", "read"):
        kind = payload.get("kind") or payload.get("scope") or "all"
        key = payload.get("key") or payload.get("id") or payload.get("page")
        limit = payload.get("limit", 20)
        result = retrieve_memory(kind=kind, key=key, limit=limit)
        return json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else str(result)

    if action_key in ("write_memory", "write"):
        kind = payload.get("kind") or payload.get("scope") or "sticky"
        page_name = payload.get("page_name") or payload.get("page") or payload.get("title")
        title = payload.get("title")
        tags = payload.get("tags")
        content = payload.get("content") if "content" in payload else payload.get("text") if "text" in payload else payload
        result = write_memory(kind, content, title=title, page_name=page_name, tags=tags)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action_key in ("rewrite_memory", "rewrite", "update"):
        kind = payload.get("kind") or payload.get("scope") or "sticky"
        key = payload.get("key") or payload.get("id") or payload.get("page")
        page_name = payload.get("page_name") or payload.get("page")
        tags = payload.get("tags")
        content = payload.get("content") if "content" in payload else payload.get("text") if "text" in payload else payload
        result = rewrite_memory(kind, key, content, page_name=page_name, tags=tags)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action_key in ("delete_memory", "delete"):
        kind = payload.get("kind") or payload.get("scope") or "sticky"
        key = payload.get("key") or payload.get("id") or payload.get("page")
        result = delete_memory(kind, key)
        return json.dumps(result, ensure_ascii=False, indent=2)

    return f"[MEMORY ERROR]: Unsupported memory action '{action}'."


if __name__ == "__main__":
    _ensure_layout()
    print("Memory storage initialized.")
