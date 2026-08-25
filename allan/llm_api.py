"""LLM access layer for ALLAN.

Provider-neutral by design. `call_model` is the only entry point the rest of
ALLAN uses; everything provider-specific lives in an adapter below and is
selected by `resolve_provider`. Adding a provider means writing one adapter and
adding one registry entry -- no caller changes anywhere else.

Adapters take a normalized request and return a normalized
(thinking, text, usage) triple, so caching, token accounting and cost
estimation work the same regardless of who served the call.
"""

from pathlib import Path
from datetime import datetime, timezone
import json

TOKEN_TRACKING_FILE = Path(__file__).resolve().parent / "storage" / "token_usage.json"

# Model id prefix -> provider. Checked longest-prefix-first.
PROVIDER_PREFIXES = (
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
    ("o1-", "openai"),
    ("o3-", "openai"),
    ("ollama/", "local"),
    ("local/", "local"),
)

# USD per 1,000,000 tokens.
PRICING = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
}

# Cache reads are ~0.1x the input rate; writes are ~1.25x (5 minute TTL).
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25

# Smallest prefix (in tokens) that a cache breakpoint will actually cache.
# Below this the marker is silently ignored -- no error, just no cache.
# These are NOT monotonic across model generations, so keep the table explicit.
CACHE_MINIMUM_TOKENS = {
    "claude-opus-5": 512,
    "claude-fable-5": 512,
    "claude-opus-4-8": 1024,
    "claude-sonnet-5": 1024,
    "claude-sonnet-4-6": 1024,
    "claude-opus-4-7": 2048,
    "claude-opus-4-6": 4096,
    "claude-haiku-4-5": 4096,
}
DEFAULT_CACHE_MINIMUM_TOKENS = 4096


def cache_minimum_for(model_name):
    """Tokens a prefix must reach before caching does anything on this model."""
    return CACHE_MINIMUM_TOKENS.get(str(model_name), DEFAULT_CACHE_MINIMUM_TOKENS)


def resolve_provider(model_name, override=None):
    """Map a model id to a provider name."""
    if override:
        return str(override).lower()
    name = str(model_name or "").lower()
    for prefix, provider in sorted(PROVIDER_PREFIXES, key=lambda p: -len(p[0])):
        if name.startswith(prefix):
            return provider
    return "anthropic"


# Anthropic allows 4 cache breakpoints per request; we use at most 2.
MAX_CACHE_BLOCKS = 4


def _as_blocks(cached_context):
    """Normalize cached_context (None | str | list[str]) to a list of non-empty blocks.

    If a caller passes more blocks than there are breakpoints to spare, the
    middle ones are joined so the first and last stay markable.
    """
    if not cached_context:
        return []
    if isinstance(cached_context, str):
        return [cached_context]
    blocks = [str(b) for b in cached_context if str(b or "").strip()]
    if len(blocks) > MAX_CACHE_BLOCKS:
        blocks = [blocks[0], "\n\n".join(blocks[1:-1]), blocks[-1]]
    return blocks


def _empty_usage():
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
    }


def estimate_cost(model_name, usage):
    """Rough USD cost for one call. Returns None for unpriced models."""
    rates = PRICING.get(str(model_name))
    if not rates:
        return None
    per_token_in = rates["input"] / 1_000_000
    per_token_out = rates["output"] / 1_000_000
    return (
        usage.get("input_tokens", 0) * per_token_in
        + usage.get("cache_read_tokens", 0) * per_token_in * CACHE_READ_MULTIPLIER
        + usage.get("cache_write_tokens", 0) * per_token_in * CACHE_WRITE_MULTIPLIER
        + usage.get("output_tokens", 0) * per_token_out
    )


# --------------------------------------------------------------------------
# Provider adapters
#
# Each takes (prompt, system_prompt, cached_context, model_name, max_tokens,
# cache) and returns (thinking, text, usage). `cached_context` is stable text
# that should sit in front of `prompt` behind a cache breakpoint.
# --------------------------------------------------------------------------

def _call_anthropic(prompt, system_prompt, cached_context, model_name, max_tokens, cache):
    try:
        from anthropic import Anthropic
    except ImportError:
        print("Anthropic module not found. Install it with: pip install anthropic")
        return None, None, _empty_usage()

    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Anthropic API key not found. Please set it up in the .env file.")
        return None, None, _empty_usage()

    system_blocks = [{"type": "text", "text": system_prompt or ""}]

    # Breakpoints go at the end of the stable region; anything after them varies
    # per call and must stay outside the cached prefix.
    #
    # With several context blocks (agent loop: frozen context, then one block per
    # observation) we mark the FIRST and the LAST. The first pins the standing
    # context so it is always readable. The last extends the cached prefix through
    # the newest observation -- because the blocks only ever grow by appending, the
    # next call's final breakpoint finds this entry via the 20-block lookback and
    # reads the whole scratchpad instead of reprocessing it.
    context_blocks = _as_blocks(cached_context)
    if context_blocks:
        user_blocks = [{"type": "text", "text": text} for text in context_blocks]
        user_blocks.append({"type": "text", "text": prompt})
        if cache:
            marks = {0, len(context_blocks) - 1}  # never marks the volatile prompt
            for index in marks:
                user_blocks[index]["cache_control"] = {"type": "ephemeral"}
    else:
        user_blocks = [{"type": "text", "text": prompt}]
        if cache:
            system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user_blocks}],
        )
    except Exception as e:
        print(f"API Network Error: {e}")
        return None, None, _empty_usage()

    thinking_content = ""
    text_content = ""
    for block in response.content:
        if block.type == "thinking":
            thinking_content += block.thinking
        elif block.type == "text":
            text_content += block.text

    raw = getattr(response, "usage", None)

    def _field(name, *aliases):
        for key in (name,) + aliases:
            if isinstance(raw, dict):
                value = raw.get(key)
            else:
                value = getattr(raw, key, None)
            if value is not None:
                return int(value)
        return 0

    usage = {
        "input_tokens": _field("input_tokens", "prompt_tokens"),
        "output_tokens": _field("output_tokens", "completion_tokens"),
        "cache_read_tokens": _field("cache_read_input_tokens"),
        "cache_write_tokens": _field("cache_creation_input_tokens"),
    }
    # input_tokens is the uncached remainder only -- real prompt size is the sum.
    usage["total_tokens"] = (
        usage["input_tokens"]
        + usage["output_tokens"]
        + usage["cache_read_tokens"]
        + usage["cache_write_tokens"]
    )
    return thinking_content, text_content, usage


def _call_openai(prompt, system_prompt, cached_context, model_name, max_tokens, cache):
    """Not implemented yet.

    Shape for whoever writes it: OpenAI caches long prefixes automatically, so
    there is no breakpoint to place -- concatenate cached_context ahead of
    prompt in the same user message and keep that prefix byte-stable. Read the
    cache counters off usage.prompt_tokens_details.cached_tokens and map them
    onto the same normalized keys as _empty_usage().
    """
    print(f"Provider 'openai' is not implemented yet (model '{model_name}').")
    return None, None, _empty_usage()


def _call_local(prompt, system_prompt, cached_context, model_name, max_tokens, cache):
    """Not implemented yet. Local runtimes have no prompt cache to manage."""
    print(f"Provider 'local' is not implemented yet (model '{model_name}').")
    return None, None, _empty_usage()


PROVIDER_ADAPTERS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "local": _call_local,
}


def call_model(
    prompt,
    model_name="claude-sonnet-5",
    effort_level=None,
    max_tokens=1000,
    system_prompt="",
    cached_context=None,
    cache=True,
    provider=None,
):
    """Send one request to a model and return (thinking, text).

    cached_context: stable text placed in front of `prompt` behind a cache
        breakpoint. Callers that reuse the same context across several calls
        should build it once and pass the identical string every time -- the
        cache is a byte-exact prefix match, so a single differing character
        anywhere in it costs the whole hit.
    cache: set False to skip the breakpoint entirely.
    """
    provider_name = resolve_provider(model_name, provider)
    adapter = PROVIDER_ADAPTERS.get(provider_name)
    if adapter is None:
        print(f"Unknown provider '{provider_name}' for model '{model_name}'.")
        return None, None

    thinking, text, usage = adapter(
        prompt, system_prompt, cached_context, model_name, max_tokens, cache
    )
    _record_token_usage(model_name, provider_name, usage)
    return thinking, text


# --------------------------------------------------------------------------
# Token accounting
# --------------------------------------------------------------------------

def _blank_payload():
    return {
        "total_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_cache_write_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "models": {},
        "events": [],
    }


def _ensure_token_tracking_file():
    TOKEN_TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_TRACKING_FILE.exists():
        with open(TOKEN_TRACKING_FILE, "w", encoding="utf-8") as f:
            json.dump(_blank_payload(), f, ensure_ascii=False, indent=2)
            f.write("\n")


def get_global_token_usage():
    _ensure_token_tracking_file()
    try:
        with open(TOKEN_TRACKING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _blank_payload()


def _record_token_usage(model_name, provider_name, usage):
    _ensure_token_tracking_file()
    model_key = str(model_name or "unknown")
    usage = {**_empty_usage(), **(usage or {})}

    payload = get_global_token_usage()
    for key in ("total_calls", "total_input_tokens", "total_output_tokens",
                "total_cache_read_tokens", "total_cache_write_tokens", "total_tokens"):
        payload.setdefault(key, 0)
    payload.setdefault("estimated_cost_usd", 0.0)

    cost = estimate_cost(model_key, usage) or 0.0

    payload["total_calls"] += 1
    payload["total_input_tokens"] += usage["input_tokens"]
    payload["total_output_tokens"] += usage["output_tokens"]
    payload["total_cache_read_tokens"] += usage["cache_read_tokens"]
    payload["total_cache_write_tokens"] += usage["cache_write_tokens"]
    payload["total_tokens"] += usage["total_tokens"]
    payload["estimated_cost_usd"] = round(payload["estimated_cost_usd"] + cost, 6)

    bucket = payload.setdefault("models", {}).setdefault(model_key, {
        "provider": provider_name,
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    })
    bucket["provider"] = provider_name
    bucket["calls"] = int(bucket.get("calls", 0)) + 1
    for field in ("input_tokens", "output_tokens", "cache_read_tokens",
                  "cache_write_tokens", "total_tokens"):
        bucket[field] = int(bucket.get(field, 0)) + usage[field]
    bucket["estimated_cost_usd"] = round(float(bucket.get("estimated_cost_usd", 0.0)) + cost, 6)

    payload.setdefault("events", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider_name,
        "model": model_key,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_read_tokens": usage["cache_read_tokens"],
        "cache_write_tokens": usage["cache_write_tokens"],
        "total_tokens": usage["total_tokens"],
        "estimated_cost_usd": round(cost, 6),
    })

    with open(TOKEN_TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def usage_report():
    """Plain-text usage summary, including how well the cache is working."""
    payload = get_global_token_usage()
    reads = payload.get("total_cache_read_tokens", 0)
    writes = payload.get("total_cache_write_tokens", 0)
    fresh = payload.get("total_input_tokens", 0)
    prompt_total = reads + writes + fresh

    lines = [
        f"Calls: {payload.get('total_calls', 0)}",
        f"Prompt tokens: {prompt_total} (fresh {fresh}, cache writes {writes}, cache reads {reads})",
        f"Output tokens: {payload.get('total_output_tokens', 0)}",
        f"Estimated cost: ${payload.get('estimated_cost_usd', 0.0):.4f}",
    ]
    if prompt_total:
        lines.append(
            f"Cache hit rate: {reads / prompt_total * 100:.1f}% of prompt tokens served from cache"
        )
    if payload.get("total_calls", 0) > 1 and reads == 0:
        lines.append(
            "WARNING: no cache reads recorded. Either the stable prefix is below this "
            "model's minimum, or something inside it changes between calls."
        )
    return "\n".join(lines)


def test_connection():
    thinking, response = call_model(
        "Hello, can you respond to this prompt and briefly share your reasoning?",
        model_name="claude-haiku-4-5",
        max_tokens=200,
    )
    if response:
        print("\n--- Model Reasoning (Hidden from User) ---")
        print(thinking if thinking else "No reasoning block provided.")
        print("\n--- Model Response ---")
        print(response)
    else:
        print("Failed to get a response from the model.")


if __name__ == "__main__":
    print("Testing model connection...\n")
    test_connection()
    print("\n--- Usage ---")
    print(usage_report())
