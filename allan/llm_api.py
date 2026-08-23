from pathlib import Path
from datetime import datetime, timezone
import json

TOKEN_TRACKING_FILE = Path(__file__).resolve().parent / "storage" / "token_usage.json"


def _ensure_token_tracking_file():
    TOKEN_TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_TRACKING_FILE.exists():
        payload = {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "models": {},
            "events": []
        }
        with open(TOKEN_TRACKING_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")


def get_global_token_usage():
    _ensure_token_tracking_file()
    try:
        with open(TOKEN_TRACKING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "models": {},
            "events": []
        }


def _record_token_usage(model_name, input_tokens=None, output_tokens=None, total_tokens=None):
    _ensure_token_tracking_file()
    if model_name is None:
        model_name = "unknown"

    input_tokens = int(input_tokens) if input_tokens is not None else 0
    output_tokens = int(output_tokens) if output_tokens is not None else 0
    total_tokens = int(total_tokens) if total_tokens is not None else input_tokens + output_tokens

    with open(TOKEN_TRACKING_FILE, "r", encoding="utf-8") as f:
        try:
            payload = json.load(f)
        except Exception:
            payload = {
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "models": {},
                "events": []
            }

    payload["total_calls"] = int(payload.get("total_calls", 0)) + 1
    payload["total_input_tokens"] = int(payload.get("total_input_tokens", 0)) + input_tokens
    payload["total_output_tokens"] = int(payload.get("total_output_tokens", 0)) + output_tokens
    payload["total_tokens"] = int(payload.get("total_tokens", 0)) + total_tokens

    model_bucket = payload.setdefault("models", {}).setdefault(str(model_name), {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    })
    model_bucket["calls"] = int(model_bucket.get("calls", 0)) + 1
    model_bucket["input_tokens"] = int(model_bucket.get("input_tokens", 0)) + input_tokens
    model_bucket["output_tokens"] = int(model_bucket.get("output_tokens", 0)) + output_tokens
    model_bucket["total_tokens"] = int(model_bucket.get("total_tokens", 0)) + total_tokens

    payload.setdefault("events", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": str(model_name),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    })

    with open(TOKEN_TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def call_model(prompt, model_name="claude-sonnet-5", effort_level=None, max_tokens=1000, system_prompt=""):

    ## FOR NOW THIS WILL ONLEY WORK WITH ANTHROPIC MODELS, BUT WE CAN ADD MORE LATER

    ## Model_name/effort level thing is pretty bad, because we want to just call an effort level and be done with it.
    ## There should be a mapping of effort level to model name, but for now we will just use the model name directly.
    ## model_name should also decide provider, same time and delay.

    try:
        import anthropic
        from anthropic import Anthropic
    except:
        anthropic = None
        print("Anthropic module not found. Please install it to use the model API.") 
        return None, None

    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())

    api_key=os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        print("Anthropic API key not found. Please set it up in the .env file.")
        return None, None
    
    #Call the model using the anthropic library, wrapped in its own error handling
    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            system = system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
    except Exception as e:
        print(f"API Network Error: {e}")
        return None, None

    # Separate thinking from text
    thinking_content = ""
    text_content = ""

    for block in response.content:
        if block.type == "thinking":
            # Anthropic's thinking block uses the .thinking attribute
            thinking_content += block.thinking
        elif block.type == "text":
            text_content += block.text

    usage = getattr(response, "usage", None)
    input_tokens = None
    output_tokens = None
    total_tokens = None

    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is None:
            input_tokens = usage.get("prompt_tokens")
        if output_tokens is None:
            output_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
    elif usage is not None:
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if input_tokens is None:
            input_tokens = getattr(usage, "prompt_tokens", None)
        if output_tokens is None:
            output_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)

    if input_tokens is not None and output_tokens is not None and total_tokens is None:
        total_tokens = input_tokens + output_tokens

    _record_token_usage(model_name, input_tokens, output_tokens, total_tokens)

    return thinking_content, text_content 







def test_connection():
    prompt = "Hello, can you respond to this prompt and briefly share your reasoning?"
    # Unpack the tuple returned by the updated function
    thinking, response = call_model(prompt, model_name="claude-sonnet-5", max_tokens=200)
    
    if response:
        print("\n--- Model Reasoning (Hidden from User) ---")
        print(thinking if thinking else "No reasoning block provided.")
        print("\n--- Model Response ---")
        print(response)
    else:
        print("Failed to get a response from the model.")

if __name__ == "__main__":
    print("Testing model connection...\n\n")
    test_connection()
    stall = input("\n\nPress Enter to exit...")