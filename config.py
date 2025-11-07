# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    MONGO_URI = os.getenv('MONGO_URI')
    MONGO_DB  = os.getenv('MONGO_DB', 'school_db')
    SECRET_KEY = os.getenv('SECRET_KEY', 'fallback-secret-key')

    def __init__(self):
        if not self.MONGO_URI:
            raise ValueError("MONGO_URI is required in .env")
        if not self.SECRET_KEY:
            raise ValueError("SECRET_KEY is required in .env")