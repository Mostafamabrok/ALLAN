#This file will contain the functions for doing requests with the API.
#This removes excess clutter from other files and keeps things easy to work on in the future.

class Conversation:
    def __init__(self, permanence, model, api_type="ollama", history = ""): #Permanance is a boolean.
        self.api_type = api_type
        self.permanence = permanence
        self.model = model
        self.system_prompt = """Your name is ALLAN and you are a helpful assistant.
                                You have a variety of functions at your disposal.
                                Here are your functions. You can call them by simply saying them like this: <[function_name]>.
                                <open_chrome>, <open_edge>, <press_key[key]>, <restart_conversation.>
                                I have an automated tool set up that reads what you says and executes functions that you say like the ones above, but you must say them in that exact way.
                                I CAN NOT call these functions. YOU call the functions by saying them (ie. "Of course I can open Chrome! <open_chrome>"). YOU are my assistant."""

        self.history = history # History is for loading previous conversations.
        self.called_functions = []

        if self.history == "":
            self.messages = [{"role": "system", "content": self.system_prompt}] #Stores conversation history as a list of dictionaries.
        else: 
            self.messages = self.history

    def send(self, message):

        import re

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
        
        self.called_functions = []

        response_funcs = re.findall(r"<[^<>]+>", self.latest_response)
        for func in response_funcs:
            self.called_functions.append(func)

    def terminal_chat(self):
        while True:
            user_input = input("You: ")

            if user_input.lower() == "exit":
                input("Press enter to close window. ")
                break

            self.send(user_input)
            print(self.model + ": " + self.latest_response)
            #DEBUG CODE: print("CALLED FUNCITIONS: " + str(self.called_functions))
    

    def voice_message(self):
        import speech_recognition as sr
        import pyttsx3

        recognizer = sr.Recognizer()
        engine = pyttsx3.init()
        
        with sr.Microphone() as source:
            print("SPEAK: ")
            recognizer.adjust_for_ambient_noise(source)
            audio = recognizer.listen(source)

        try:
            text = recognizer.recognize_google(audio)
            print("You said: ", text)
            self.send(text)
            print(self.model + ": " + self.latest_response)
            engine.say(self.latest_response)
            engine.runAndWait()
            return text
        
        except sr.UnknownValueError:
            print("Audio Incomprehensible")
        except sr.RequestError:
            print("Could not request results, internet connection.")

    def voice_chat(self):
        while True:
            self.voice_message()
    



    
    
    
def test_run():
    x = Conversation(True, "gemma3:12b")
    #x.send("What is your name?")
    #print(x.latest_response)

    x.voice_chat()

    #print(x.messages)

if __name__ == "main":
    test_run()


