from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class OrderIn(BaseModel):
    account_id: str
    instrument_token: int
    quantity: int
    price: float
    order_type: str        # "MARKET" | "LIMIT"
    transaction_type: str  # "BUY" | "SELL"
    product: str = "NRML"   # "MIS" | "CNC" | "CO" | "BO"

class ReplicateOrderIn(BaseModel):
    master_account_id: str
    instrument_token: int
    master_quantity: int
    price: float
    order_type: str
    transaction_type: str
    product: str = "NRML"
    # Replication strategy: pass child accounts or use pre-configured list
    child_accounts: Optional[list] = None

class OrderResponse(BaseModel):
    account_id: str
    order_id: str
    status: str
    quantity: int
    filled_quantity: int
    average_price: float
    placed_at: datetime
