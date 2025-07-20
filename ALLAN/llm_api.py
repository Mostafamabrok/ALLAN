# llm_api.py
# This file is dedicated to handling communication with the LLM.
from utils import log

try:
    import ollama
except ImportError:
    log(f"Error Importing Ollama!", "LLM_API")
    ollama = None

def call_model(model: str, context: list) -> str:
    if not ollama:
        return "Ollama library not installed."

    try:
        response = ollama.chat(model=model, messages=context)
        return response['message']['content']
    except Exception as e:
        log(f"ERROR calling Ollama: {e}", "LLM_API")
        return f"Error calling Ollama: {e}"

