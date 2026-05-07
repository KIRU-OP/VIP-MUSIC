#
# Copyright (C) 2021-2022 by KIRU-OP@Github, < https://github.com/KIRU-OP >.
#
# This file is part of < https://github.com/KIRU-OP/VIPMUSIC > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/KIRU-OP/VIPMUSIC/blob/master/LICENSE >
#
# All rights reserved.
import sys
from pyrogram import Client
import config
from ..logging import LOGGER

# Global lists to store assistant info
assistants = []
assistantids = []

class Userbot(Client):
    def __init__(self):
        self.one = None
        self.two = None
        self.three = None
        self.four = None
        self.five = None
        
        # List of session strings from config
        self.sessions = [
            config.STRING1, 
            config.STRING2, 
            config.STRING3, 
            config.STRING4, 
            config.STRING5
        ]

    async def start(self):
        LOGGER(__name__).info("Starting Assistant Clients...")
        
        # Mapping for dynamic attribute assignment (self.one, self.two, etc.)
        client_names = ["one", "two", "three", "four", "five"]

        for i, session in enumerate(self.sessions):
            if not session:
                continue

            # Initialize Client
            client = Client(
                name=f"AnonXAss{i+1}",
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                session_string=str(session),
                no_updates=True,
            )

            try:
                await client.start()
                
                # Auto-join specific chats based on assistant number
                try:
                    if i == 4:  # Assistant 5 logic
                        await client.join_chat("FRIEND_HUB_CHATTING_GROUP")
                        await client.join_chat("about_deadly_venom")
                    else:
                        await client.join_chat("https://t.me/+6Zg_OWIyoS5mYzQ9")
                except Exception:
                    pass  # Ignore if already in chat or join fails

                # Log verification
                try:
                    await client.send_message(config.LOGGER_ID, f"Assistant {i+1} Started Successfully")
                except Exception:
                    LOGGER(__name__).error(
                        f"Assistant {i+1} failed to access the Log Group. "
                        "Ensure the assistant is added to your log group and promoted as admin!"
                    )
                    sys.exit()

                # Get Assistant Details
                me = await client.get_me()
                if not me.username:
                    LOGGER(__name__).error(f"Assistant {i+1} has no username. Please set one and restart.")
                    sys.exit()

                client.id = me.id
                client.name = me.mention
                client.username = me.username
                
                # Update global tracking
                assistants.append(i + 1)
                assistantids.append(me.id)
                
                # Dynamically set self.one, self.two, etc.
                setattr(self, client_names[i], client)
                
                LOGGER(__name__).info(f"Assistant {i+1} Started as {client.name}")

            except Exception as e:
                LOGGER(__name__).error(f"Assistant {i+1} failed to start: {str(e)}")
                continue

    async def stop(self):
        LOGGER(__name__).info("Stopping Assistant Clients...")
        # Iterating through potential clients to stop them
        for attr in ["one", "two", "three", "four", "five"]:
            client = getattr(self, attr)
            if client:
                try:
                    await client.stop()
                except Exception:
                    pass
