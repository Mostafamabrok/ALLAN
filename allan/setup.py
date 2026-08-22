print("Setting up ALLAN")

def set_api_key():

    from pathlib import Path

    file_path = Path(".env")

    if file_path.exists():
        print(".env file already exists. Skipping API key setup.")
        return

    key_provider =input("Who is your API provider? (OpenAI/Anthropic/Local): ").strip().lower()

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
    set_api_key()


