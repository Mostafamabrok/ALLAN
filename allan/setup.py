print("Setting up ALLAN")

from pathlib import Path
import json
import os

SETTINGS_PATH = Path(__file__).parent / "Allan_Prime_Settings.json"
GITIGNORE_PATH = Path(__file__).parent.parent / ".gitignore"

DEFAULT_SETTINGS = {
    "model_name": "claude-sonnet-5",
    "max_tokens": 1024,
    "default_interface": "terminal",
    "available_tools": ["web_search", "web_dive"],
    "interface_rules": {
        "terminal": {
            "label": "terminal",
            "forbidden": [
                "markdown headings",
                "markdown tables",
                "code fences",
                "emoji",
                "long multi-line blocks",
                "xml-like formatting in user output"
            ],
            "required": [
                "plain text only",
                "short paragraphs",
                "no markdown",
                "no tool tags in user-facing output"
            ]
        },
        "voice": {
            "label": "voice",
            "forbidden": [
                "markdown",
                "bullet lists",
                "tool tags",
                "very long sentences",
                "excessive punctuation"
            ],
            "required": [
                "spoken-language style",
                "brief and natural responses",
                "clear direct answer",
                "no hidden system formatting"
            ]
        }
    },
    "system_prompt": "You are ALLAN (Autonomous Language Learning Agent Network), an advanced, highly capable AI assistant.\nYou maintain two conversation threads: internal (private reasoning and tool decisions) and user (visible replies).\nDo all tool work in the internal thread first, then produce a single user-facing reply. Respect the active interface formatting rules.\n\nTOOL USAGE INSTRUCTIONS:\n- All tool calls MUST be emitted inside the internal thread and wrapped exactly in <tool> JSON tags. Do NOT include any explanation or other text inside the tags.\n- Tool format: <tool>{\"name\": \"tool_name\", \"args\": { ... }}</tool>\n\nAVAILABLE TOOL CONTRACTS (examples):\n1) web_search\n   - Purpose: perform a web search for a query and return a short list of results (title, URL, snippet).\n   - Example call: <tool>{\"name\": \"web_search\", \"args\": {\"query\": \"latest AI research\", \"max_results\": 3}}</tool>\n\n2) web_dive\n   - Purpose: fetch and extract readable text content from a single web page URL (no JS execution).\n   - Example call: <tool>{\"name\": \"web_dive\", \"args\": {\"url\": \"https://example.com/article\", \"max_chars\": 2000}}</tool>\n\nRESPONDING RULES:\n- Tools may print internal data, but the final user-facing reply MUST NOT contain raw tool tags or internal reasoning.\n- When a tool finishes, summarize its findings in plain user-friendly language that respects the active interface rules (use <user_reply>...</user_reply> to mark the final reply).\n- If you would otherwise say \"I’m processing that internally before answering,\" automatically run a follow-up internal step to produce the user-facing summary once tool results are available.\n\nKeep all tool logic and intermediate steps internal; only return the final, cleaned-up answer to the user."
}


def ensure_settings():
    # Create settings file with defaults if missing
    if not SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"Created default settings at: {SETTINGS_PATH}")

    # Ensure settings file is gitignored
    try:
        if GITIGNORE_PATH.exists():
            gitignore_text = GITIGNORE_PATH.read_text(encoding="utf-8")
            rel = os.path.relpath(SETTINGS_PATH, GITIGNORE_PATH.parent)
            if rel not in gitignore_text:
                with open(GITIGNORE_PATH, "a", encoding="utf-8") as g:
                    g.write(f"\n# ALLAN runtime settings\n{rel}\n")
                print(f"Added {rel} to .gitignore")
        else:
            # create a .gitignore at repo root
            with open(GITIGNORE_PATH, "w", encoding="utf-8") as g:
                g.write(f"# ALLAN runtime settings\n{os.path.relpath(SETTINGS_PATH, GITIGNORE_PATH.parent)}\n")
            print(f"Created .gitignore and added settings entry: {GITIGNORE_PATH}")
    except Exception as e:
        print(f"Warning: could not update .gitignore: {e}")


def set_api_key():
    file_path = Path(".env")

    if file_path.exists():
        print(".env file already exists. Skipping API key setup.")
        return

    key_provider = input("Who is your API provider? (OpenAI/Anthropic/Local): ").strip().lower()

    providers = ["openai", "anthropic", "local"]

    if key_provider not in providers:
        print("Invalid API provider. Please choose either 'OpenAI' or 'Anthropic'.")
        raise ValueError("Invalid API provider. Please choose either 'OpenAI' or 'Anthropic'.")

    if key_provider == "openai":
        api_key = input("Please enter your OpenAI API key: ")
        with open(".env", "w") as f:
            f.write(f"OPENAI_API_KEY={api_key}\n")

        print("OpenAI API key has been set up successfully.")

    if key_provider == "anthropic":
        api_key = input("Please enter your Anthropic API key: ")
        with open(".env", "w") as f:
            f.write(f"ANTHROPIC_API_KEY={api_key}\n")
        print("Anthropic API key has been set up successfully.")

    if key_provider == "local":
        print("STILL IN PROGRESS: Local API key setup is not yet implemented.")


if __name__ == "__main__":
    ensure_settings()
    set_api_key()
