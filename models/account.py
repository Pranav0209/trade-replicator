from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class LinkAccountIn(BaseModel):
    account_id: str          # Zerodha account ID (e.g., "ABC123")
    api_key: str             # Zerodha API key
    api_secret: str          # Zerodha API secret

class AccountResponse(BaseModel):
    account_id: str
    api_key: str
    api_secret: str
    access_token: Optional[str] = None
    request_token: Optional[str] = None
    status: str              # "pending" | "connected"
    linked_at: Optional[datetime] = None
    children: List[str] = []  # List of child account IDs

class FundsResponse(BaseModel):
    account_id: str
    equity: dict
    commodity: dict
