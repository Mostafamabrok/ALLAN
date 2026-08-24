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
            from allanprime import has_pending_tasks
            if has_pending_tasks():
                print("Cannot exit while tasks remain. Finish or mark the task list as done first.")
                continue
            print("Shutting down ALLAN terminal. Goodbye!")
            break

        if user_input.lower() == "clear":
            clear_history()
            print("Persistent conversation history cleared.")
            continue
            
        if not user_input.strip():
            continue
        
        # Route the input to the main engine with the active interface context.
        response = ALLAN_prime(user_input, interface_name="terminal")
        
        # Output the generated response to the user space
        print(f"ALLAN: {response}")


if __name__ == "__main__":
    terminal_interface()