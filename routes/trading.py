from fastapi import APIRouter, HTTPException
from datetime import datetime
from kiteconnect import KiteConnect
from db.storage import db
from models.order import OrderIn, ReplicateOrderIn, OrderResponse
from core.replicator import replicate_order

router = APIRouter()

@router.post("/place-order")
async def place_order(body: OrderIn) -> OrderResponse:
    """
    Place a single order on a Zerodha account.
    """
    acc = await db.accounts.find_one({"account_id": body.account_id})
    if not acc:
        raise HTTPException(404, f"Account {body.account_id} not found")
    
    if acc["status"] != "connected":
        raise HTTPException(400, f"Account {body.account_id} not connected")
    
    try:
        kite = KiteConnect(api_key=acc["api_key"])
        kite.set_access_token(acc["access_token"])
        
        order_id = kite.place_order(
            tradingsymbol="",  # Will set from token lookup
            exchange="NSE",
            transaction_type=body.transaction_type,
            quantity=body.quantity,
            order_type=body.order_type,
            price=body.price,
            product=body.product
        )
        
        # Store order in DB
        import uuid
        order_doc = {
            "id": str(uuid.uuid4()),
            "account_id": body.account_id,
            "order_id": order_id,
            "instrument_token": body.instrument_token,
            "quantity": body.quantity,
            "price": body.price,
            "status": "placed",
            "placed_at": datetime.utcnow().isoformat()
        }
        await db.orders.insert_one(order_doc)
        
        return OrderResponse(
            account_id=body.account_id,
            order_id=order_id,
            status="placed",
            quantity=body.quantity,
            filled_quantity=0,
            average_price=body.price,
            placed_at=datetime.utcnow()
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to place order: {e}")

@router.post("/replicate")
async def replicate(body: ReplicateOrderIn):
    """
    Replicate a master account order to child accounts proportionally.
    
    Replication logic:
    - Get child account funds
    - Calculate proportional quantities based on capital
    - Place orders on all child accounts
    """
    master = await db.accounts.find_one({"account_id": body.master_account_id})
    if not master:
        raise HTTPException(404, f"Master account {body.master_account_id} not found")
    
    # Use provided children or master's configured children
    child_ids = body.child_accounts or master.get("children", [])
    if not child_ids:
        raise HTTPException(400, "No child accounts configured for replication")
    
    try:
        # Replicate the order
        results = await replicate_order(
            master_account_id=body.master_account_id,
            child_account_ids=child_ids,
            instrument_token=body.instrument_token,
            master_quantity=body.master_quantity,
            price=body.price,
            order_type=body.order_type,
            transaction_type=body.transaction_type,
            product=body.product
        )
        
        return {
            "status": "ok",
            "master_account_id": body.master_account_id,
            "replicated_to": len(results),
            "results": results
        }
    except Exception as e:
        raise HTTPException(500, f"Replication failed: {e}")

@router.get("/orders/{account_id}")
async def get_orders(account_id: str):
    """
    Get all orders for an account.
    """
    orders = await db.orders.find({"account_id": account_id}).to_list(100)
    return {
        "account_id": account_id,
        "count": len(orders),
        "orders": orders
    }
