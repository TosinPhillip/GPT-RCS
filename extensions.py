# extensions.py
from pymongo import MongoClient
from flask import current_app
import logging
import time

mongo = None   # will hold the MongoClient instance

def init_mongo(app):
    """
    Create a MongoClient with auto-reconnect and ping the server.
    Called once when the Flask app starts.
    """
    global mongo
    uri = app.config.get('MONGO_URI')
    if not uri:
        raise ValueError("MONGO_URI is missing in .env")

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            client = MongoClient(
                uri,
                serverSelectionTimeoutMS=5000,   # fast fail
                retryWrites=True,
                maxPoolSize=10,
                connectTimeoutMS=10000,
            )
            # Force a ping to verify the connection
            client.admin.command('ping')
            mongo = client[app.config.get('MONGO_DB', 'school_db')]
            print("MongoDB connected successfully!")
            logging.info("MongoDB connected")
            return
        except Exception as e:
            logging.warning(f"Attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(3)
    raise ConnectionError("Could not connect to MongoDB after several attempts")