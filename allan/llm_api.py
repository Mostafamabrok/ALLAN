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