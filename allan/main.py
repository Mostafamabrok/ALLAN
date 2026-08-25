from allanprime import (
    ALLAN_prime,
    INTERFACE_RULES,
    clear_history,
    has_pending_tasks,
    init_storage,
)
from llm_api import usage_report
from user_interaction_space import make_progress_handler

INTERFACE = "terminal"


def terminal_interface():
    """User-facing loop. Routes data to ALLAN_prime."""
    init_storage()

    # The engine emits structured progress events; this decides what a terminal
    # shows. A voice front end would build the same handler with its own name
    # and get near-silence instead, without the engine changing at all.
    show_progress = make_progress_handler(INTERFACE, INTERFACE_RULES, sink=print)

    print("Welcome to the ALLAN terminal interface!")
    print("Commands: 'exit' to quit, 'clear' to wipe history, 'usage' for token spend.")

    while True:
        user_input = input("\nYou: ")

        if user_input.lower() == "exit":
            if has_pending_tasks():
                print("Tasks are still pending. Finish them, or type 'clear tasks' to drop them.")
                continue
            print("Shutting down ALLAN terminal. Goodbye!")
            break

        if user_input.lower() == "clear":
            clear_history()
            print("Persistent conversation history cleared.")
            continue

        if user_input.lower() == "usage":
            print(usage_report())
            continue

        if not user_input.strip():
            continue

        response = ALLAN_prime(user_input, interface_name=INTERFACE, on_progress=show_progress)

        print(f"ALLAN: {response}")


if __name__ == "__main__":
    terminal_interface()
