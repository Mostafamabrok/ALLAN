from llm_api import call_model
from allanprime import init_storage, clear_history, ALLAN_prime

def terminal_interface():
    """User-facing loop. Routes data to ALLAN_prime."""
    # Ensure storage exists before starting the chat loop
    init_storage()
    
    print("Welcome to the ALLAN terminal interface!")
    print("Type 'exit' to quit or 'clear' to wipe persistent memory.")

    while True:
        user_input = input("\nYou: ")
        
        if user_input.lower() == "exit":
            print("Shutting down ALLAN terminal. Goodbye!")
            break

        if user_input.lower() == "clear":
            clear_history()
            print("Persistent conversation history cleared.")
            continue
            
        if not user_input.strip():
            continue
        
        # Route the input to the main engine
        response = ALLAN_prime(user_input)
        
        # Output the generated response to the user space
        print(f"ALLAN: {response}")


if __name__ == "__main__":
    terminal_interface()