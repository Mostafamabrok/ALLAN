# llm_api.py
# This file is dedicated to handling communication with the LLM.

try:
    import ollama
except ImportError:
    print("Warning: The 'ollama' library is not installed.")
    ollama = None

def call_model(model: str, context: list) -> str:
    """
    Calls the Ollama API with a specific model and context.
    
    Args:
        model (str): The name of the Ollama model to use.
        context (list): The list of message dictionaries for the conversation.

    Returns:
        str: The text content of the model's response or an error message.
    """
    if not ollama:
        return "Ollama library not installed."

    try:
        # This is the direct API call to the Ollama service.
        response = ollama.chat(model=model, messages=context)
        return response['message']['content']
    except Exception as e:
        # In a real app, this would go to a more robust logger.
        print(f"ERROR calling Ollama: {e}")
        return f"Error calling Ollama: {e}"

