def call_model(prompt, model_name="claude-sonnet-5", effort_level=None, max_tokens=1000):

    ## FOR NOW THIS WILL ONLEY WORK WITH ANTHROPIC MODELS, BUT WE CAN ADD MORE LATER

    ## Model_name/effort level thing is pretty bad, because we want to just call an effort level and be done with it.
    ## There should be a mapping of effort level to model name, but for now we will just use the model name directly.


    try:
        import anthropic
        from anthropic import Anthropic

    except:
        anthropic = None
        print("Anthropic module not found. Please install it to use the model API.") 

    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())

    api_key=os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        print("Anthropic API key not found. Please set it up in the .env file.")
        return None
    
    # Example code to call the model using the anthropic library
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.content[0].text 
    #This is just plain bad. Needs to adapt to anthropic/openai/gemini/ollama. Later. Keep this in mind.


def test_connection():
    prompt = "Hello, can you respond to this prompt?"
    response = call_model(prompt, model_name="claude-sonnet-5", max_tokens=50)
    if response:
        print("Model response:", response)
    else:
        print("Failed to get a response from the model.")

if __name__ == "__main__":
    print("Testing model connection...\n\n")
    test_connection()
    stall = input("\n\nPress Enter to exit...")