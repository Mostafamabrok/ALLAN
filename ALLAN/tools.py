from utils import log

async def send_message(agent, recipient: str, message: str):
    """A tool that allows an agent to send a message to another agent via the network."""
    if recipient and message:
        await agent.network_manager.send_message(
            recipient_name=recipient,
            message_content=message,
            sender_name=agent.name
        )
    else:
        log("ERROR: send_message tool called with missing arguments.", source=agent.name)

async def work_complete(agent):
    log("Task processing is complete. Awaiting next message.", source=agent.name)
    # This is a placeholder for future state management.
    # For now, it just logs the completion.
