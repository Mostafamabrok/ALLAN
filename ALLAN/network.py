import asyncio

class NetworkManager:
    def __init__(self):
        self.agents = {}

    def log(self, message: str):
        print(f"[Network LOG]: {message}")

    def register(self, agent):
        """Adds an agent to the network registry."""
        self.agents[agent.name] = agent
        self.log(f"Registered agent: {agent.name}")

    async def send_message(self, recipient_name, message_content, sender_name):
        """Routes a message to the recipient agent's inbox queue."""
        recipient = self.agents.get(recipient_name)
        if recipient:
            message = {"sender": sender_name, "content": message_content}
            await recipient.inbox.put(message)
            self.log(f"Routed message from {sender_name} to {recipient_name}")
        else:
            self.log(f"ERROR: Agent '{recipient_name}' not found.")

