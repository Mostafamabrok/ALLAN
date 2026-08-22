def call_model(prompt, model_name="haiku", effort_level=None, max_tokens=1000):

    ## FOR NOW THIS WILL ONLEY WORK WITH ANTHROPIC MODELS, BUT WE CAN ADD MORE LATER

    ## Model_name/effort level thing is pretty bad, because we want to just call an effort level and be done with it.
    ## There should be a mapping of effort level to model name, but for now we will just use the model name directly.


    try:
        import anthropic

    except:
        anthropic = None
        print("Anthropic module not found. Please install it to use the model API.") 

    import os
    from dotenv import load_dotenv

    api_key=os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        print("Anthropic API key not found. Please set it up in the .env file.")
        return None
    
    # Example code to call the model using the anthropic library
    client = anthropic.Client(api_key=api_key)
    response = client.completions.create(
        model=model_name,
        prompt=prompt,
        max_tokens=max_tokens
    )

    return response.choices[0].text