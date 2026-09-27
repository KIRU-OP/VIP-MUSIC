#
# Copyright (C) 2021-2022 by KIRU-OP@Github, < https://github.com/KIRU-OP >.
#
# This file is part of < https://github.com/KIRU-OP/VIPMUSIC > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/KIRU-OP/VIPMUSIC/blob/master/LICENSE >
#
# All rights reserved.
import sys
from motor.motor_asyncio import AsyncIOMotorClient as _mongo_client_
from pymongo import MongoClient
from pyrogram import Client
from pymongo.errors import PyMongoError

import config
from ..logging import LOGGER

# Fallback Database URL
TEMP_MONGODB = "mongodb+srv://vishalpandeynkp:Bal6Y6FZeQeoAoqV@cluster0.dzgwt.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

def initialize_database():
    global mongodb, pymongodb

    if config.MONGO_DB_URI is None:
        LOGGER(__name__).warning(
            "No MONGO_DB_URI found. Your bot will use the fallback NOBITA MUSIC database."
        )
        try:
            # Use in_memory=True to avoid creating unnecessary session files
            temp_client = Client(
                "VIPMUSIC_TEMP",
                bot_token=config.BOT_TOKEN,
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                in_memory=True,
            )
            temp_client.start()
            info = temp_client.get_me()
            username = info.username
            temp_client.stop()

            # Connecting to the fallback database using the bot's username
            _mongo_async_ = _mongo_client_(TEMP_MONGODB)
            _mongo_sync_ = MongoClient(TEMP_MONGODB)
            mongodb = _mongo_async_[username]
            pymongodb = _mongo_sync_[username]
            LOGGER(__name__).info(f"Connected to fallback database for bot: @{username}")

        except Exception as e:
            LOGGER(__name__).error(f"Failed to initialize fallback database: {e}")
            sys.exit()
    else:
        try:
            # Connecting to the user-provided MongoDB URI
            _mongo_async_ = _mongo_client_(config.MONGO_DB_URI)
            _mongo_sync_ = MongoClient(config.MONGO_DB_URI)
            
            # Using 'VIPMUSIC' as the default database name
            mongodb = _mongo_async_.VIPMUSIC
            pymongodb = _mongo_sync_.VIPMUSIC
            LOGGER(__name__).info("Custom MongoDB connection established successfully.")

        except PyMongoError as e:
            LOGGER(__name__).error(f"Invalid MONGO_DB_URI or connection error: {e}")
            sys.exit()

# Run the initialization
initialize_database()
