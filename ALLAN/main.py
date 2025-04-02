import os
import shutil

from allan_core import *

config = { #This should be editable by the user without going into the code later on. TBA
    'model'     : 'gemma3:12b',
    'permanence': True
}


def allan_terminal_ui():

    allan = Conversation(config["permanence"], config["model"])

    version_number = "0.0.1"
    
    print("\n\n\nALLAN v" + version_number)

    print("Choose an action from the prompts by typing its number and pressing enter.")
    print("1-Chat with ALLAN in the Terminal")
    print("2-Chat with ALLAN using Voice")
    print("3-Restart Conversation")
    print("4-Load old conversation")
    print("5-Exit")

    desired_action = input(": ")

    if   desired_action == "1": allan.terminal_chat()
    elif desired_action == "2": allan.voice_chat()
    elif desired_action == "3": allan = Conversation(config["permanence"], config["model"]); print("Conversation Restarted.")
    elif desired_action == "4": print("Feature is still in development. Check the Github Page for new updates.")
    elif desired_action == "5": exit()
    else: print("Please enter a valid input.\n")

    allan_terminal_ui()
    #Is there a better way to do this than recursiveness?
    #I have no idea.
    #This works for now though.

allan_terminal_ui()