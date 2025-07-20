import asyncio
from utils import log

class NetworkManager:
    def __init__(self):
        self.agents = {}

    def register(self, agent):
        """Adds an agent to the network registry."""
        self.agents[agent.name] = agent
        log(f"Registered agent: {agent.name}")

    async def send_message(self, recipient_name, message_content, sender_name):
        """Routes a message to the recipient agent's inbox queue."""
        recipient = self.agents.get(recipient_name)
        if recipient:
            message = {"sender": sender_name, "content": message_content}
            await recipient.inbox.put(message)
            log(f"Routed message from {sender_name} to {recipient_name}")
        else:
            log(f"ERROR: Agent '{recipient_name}' not found.")

