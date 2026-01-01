import os
from dotenv import load_dotenv

load_dotenv()

# Global Settings
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5")) # Seconds
DRY_RUN = True # Set to False to enable real trading

# Master Account ID
MASTER_USER_ID = os.getenv("MASTER_USER_ID", "MASTER123")

# User Configuration
# DEFINE YOUR REAL ACCOUNTS HERE
# "capital" is used for allocation logic.
ACCOUNTS = [
    {
        "user_id": MASTER_USER_ID,
        "api_key": os.getenv("MASTER_API_KEY", "master_key"),
        "api_secret": os.getenv("MASTER_API_SECRET", "master_secret"),
        "is_master": True,
        "capital": 5000000.0,
        "enabled": True
    },
    {
        "user_id": os.getenv("CHILD_A_USER_ID", "CHILD_A"),
        "api_key": os.getenv("CHILD_A_API_KEY", "child_a_key"),
        "api_secret": os.getenv("CHILD_A_API_SECRET", "child_a_secret"),
        "is_master": False,
        "capital": 500000.0,
        "enabled": True
    },

]
