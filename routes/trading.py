from fastapi import APIRouter, HTTPException

from db.storage import db


router = APIRouter()



@router.get("/orders/{account_id}")
async def get_orders(account_id: str):
    """
    Get all orders for an account.
    """
    orders = await db.orders.find({"account_id": account_id})
    return {
        "account_id": account_id,
        "count": len(orders),
        "orders": orders
    }

@router.post("/reset-strategy")
async def reset_strategy():
    """
    Force reset the strategy state to inactive.
    Useful for starting a new trade cycle manually.
    """
    try:
        from core.strategy_state import state_manager
        
        # 1. Clear Active State immediately
        state_manager.clear()
        
        # 2. Set Flag for Orchestrator to clear its memory
        state_manager.request_reset()
            
        print("[System] Strategy State Manually Reset via API. Requesting Orchestrator State Clear.")
        return {"status": "ok", "message": "Strategy state reset successfully. Orchestrator will clear memory on next tick."}
            
        print("[System] Strategy State Manually Reset via API.")
        return {"status": "ok", "message": "Strategy state reset successfully"}
    except Exception as e:
        raise HTTPException(500, f"Failed to reset strategy: {e}")
