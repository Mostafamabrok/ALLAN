import os
from llm_api import call_model

# Define storage paths globally
STORAGE_DIR = "storage"
HISTORY_FILE = os.path.join(STORAGE_DIR, "allan_prime_history.txt")

def init_storage():
    #Ensures the storage directory and history file exist.
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w") as f:
            pass

def get_history():
    #Reads the persistent history from the text file.
    with open(HISTORY_FILE, "r") as f:
        return f.read().strip()

def append_to_history(text):
    #Appends a new line of text to the persistent history file.
    with open(HISTORY_FILE, "a") as f:
        f.write(text + "\n")

def clear_history():
    #Wipes the persistent history file.
    with open(HISTORY_FILE, "w") as f:
        pass

def ALLAN_prime(user_input):

    append_to_history(f"User: {user_input}")
    
    full_history = get_history()
    prompt_context = f"{full_history}\nALLAN:"
    
    thinking, response = call_model(prompt_context, model_name="claude-sonnet-5", max_tokens=1024)
    
    # Catch the failure state explicitly handled by llm_api.py
    if response is None:
        return "System Error: The LLM API failed to return a response."
    
    if thinking:
        append_to_history(f"[ALLAN INTERNAL THOUGHT]: {thinking}")
            
    append_to_history(f"ALLAN: {response}")
    return response