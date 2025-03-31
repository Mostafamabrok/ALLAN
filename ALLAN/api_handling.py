#This file will contain the functions for doing requests with the API.
#This removes excess clutter from other files and keeps things easy to work on in the future.

class Conversation:
    def __init__(self, permanence, model, api_type="ollama", history = ""): #Permanance is a boolean.
        self.api_type = api_type
        self.permanence = permanence
        self.model = model
        self.system_prompt = """Your name is ALLAN and you are a helpful assistant.
                                You have a variety of functions at your disposal.
                                Here are your functions. You can call them by simply saying them like this: <[function_name]>
                                <open_chrome>, <open_edge>, <press_key[key]>, <restart_conversation.>
                                I have an automated tool set up that reads what you says and executes functions that you say like the ones above, but you must say them in that exact way.
                                I CAN NOT call these functions. YOU call the functions by saying them (ie. "Of course I can open Chrome! <open_chrome>"). YOU are my assistant."""
        self.history = history # History is for loading previous conversations.
        if self.history == "":
            self.messages = [{"role": "system", "content": self.system_prompt}] #Stores conversation history as a list of dictionaries.
        else: 
            self.messages = self.history

    def send(self, message):
        self.messages.append({"role": "user", "content": message})

        if self.api_type == "ollama":
            import ollama
            api_response = ollama.chat(model= self.model, messages=self.messages)
            self.latest_response = api_response['message']['content']

        if self.api_type == "openai":
            import openai
            api_response = openai.ChatCompletion.create(model = self.model, messages=self.messages)
            self.latest_response = api_response["choices"][0]["message"]
        
        self.messages.append({"role": "assistant", "content": self.latest_response})

    def terminal_chat(self):
        while True:
            user_input = input("You: ")
            if user_input.lower == "exit":
                break
            self.send(user_input)
            print(self.model + ": " + self.latest_response)

    
    
    
def test_run():
    x = Conversation(True, "deepseek-r1:7b")
    #x.send("What is your name?")
    #print(x.latest_response)

    x.terminal_chat()

    print(x.messages)

test_run()


