# main.py
import time
import json
import asyncio
import re

# ALLAN Modules
from llm_api import call_model
from network import NetworkManager

DEFAULT_ALLAN_CONFIG = {
    "name": "UnnamedAgent",
    "role": "Worker",
    "model": "gemma3",
    "system_prompt": """You are an autonomous AI agent. You process incoming messages and decide on a course of action.
You have an internal knowledge base. If a task is a question you can answer, you should answer it directly using the `send_message` tool.

To act, you must use tools. Respond with one or more tool calls in the format: [CALL: function_name(arg1="value1")]
Your available tools are:
- send_message(recipient: str, message: str)
- work_complete() -> Call this with no arguments when you have fully completed the task prompted by the message.

IMPORTANT: Always follow the [CALL: function_name(arg1="value1")] structure, even for functions with no arguments. 
IMPORTANT: If you lack the tools and the knowledge to complete a task, you must report this limitation back to the sender. Do not invent tools that are not on this list.
IMPORTANT: You must never use `send_message` with `recipient="System"`.
""",
    "job_description": "No job description provided.",
    "permissions": [],
    "superiors": [],
    "subordinates": []
}

class Allan:
    def __init__(self, config: dict, manager: NetworkManager):
        final_config = DEFAULT_ALLAN_CONFIG.copy()
        final_config.update(config)
        
        self.config = final_config
        self.name = self.config['name']
        self.network_manager = manager
        self.inbox = asyncio.Queue()
        self.message_history = []
        
    def log(self, message: str):
        print(f"[{self.name} LOG]: {message}")

    def parse_for_calls(self, text: str) -> list:
        call_pattern = r'\[CALL:\s*(\w+)\((.*?)\)\s*\]'
        matches = re.findall(call_pattern, text)
        calls = []
        for func_name, args_str in matches:
            args_pattern = r'(\w+)\s*=\s*"(.*?)"'
            args_matches = re.findall(args_pattern, args_str)
            args_dict = {key: value for key, value in args_matches}
            calls.append({"function": func_name, "args": args_dict})
        return calls

    async def execute_tool(self, tool_call: dict):
        function_name = tool_call.get("function")
        args = tool_call.get("args", {})
        
        if function_name == "send_message":
            recipient = args.get("recipient")
            message = args.get("message")
            if recipient and message:
                await self.network_manager.send_message(
                    recipient_name=recipient,
                    message_content=message,
                    sender_name=self.name
                )
            else:
                self.log("ERROR: send_message tool called with missing arguments.")
        
        elif function_name == "work_complete":
            self.log("Task processing is complete. Awaiting next message.")

        else:
            self.log(f"ERROR: Attempted to call unknown tool '{function_name}'.")

    async def run(self):
        self.log("Event loop started. Awaiting messages.")
        while True:
            incoming_message = await self.inbox.get()
            
            sender = incoming_message['sender']
            content = incoming_message['content']
            
            prompt = f"You have received a message from '{sender}'. The message is: '{content}'. Based on your role, tools, and our conversation history, what action(s) will you take?"
            
            self.message_history.append({"role": "user", "content": prompt})

            context = [
                {"role": "system", "content": self.config['system_prompt']}
            ] + self.message_history
            
            response_plan = call_model(self.config['model'], context)
            
            self.message_history.append({"role": "assistant", "content": response_plan})

            self.log(f"Generated plan: {response_plan}")

            tool_calls = self.parse_for_calls(response_plan)
            if tool_calls:
                self.log(f"Executing actions: {tool_calls}")
                for call in tool_calls:
                    await self.execute_tool(call)
            else:
                self.log("No tool calls found in plan.")
            
            self.inbox.task_done()


async def main():
    print("--- Initializing Agent Network ---")
    network = NetworkManager()

    master_config = {"name": "MasterBot", "role": "Manager", "job_description": "Delegate tasks to workers."}
    worker_config = {"name": "WorkerBot", "role": "Worker", "job_description": "Execute tasks from my manager."}
    
    master = Allan(master_config, network)
    worker = Allan(worker_config, network)

    network.register(master)
    network.register(worker)

    asyncio.create_task(master.run())
    asyncio.create_task(worker.run())

    print("\n--- Kicking off conversation ---")
    await asyncio.sleep(1)

    initial_prompt = "We need to know what the capital of Egypt is. Please delegate this task to WorkerBot."
    await network.send_message(
        recipient_name="MasterBot",
        message_content=initial_prompt,
        sender_name="System"
    )

    await asyncio.sleep(30)
    print("\n--- Test finished ---")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n--- Shutting down network ---")
