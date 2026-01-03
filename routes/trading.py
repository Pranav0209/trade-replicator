from fastapi import APIRouter, HTTPException

from db.storage import db


router = APIRouter()



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

@router.post("/reset-strategy")
async def reset_strategy():
    """
    Force reset the strategy state to inactive.
    Useful for starting a new trade cycle manually.
    """
    try:
        import json
        state_file = "data/strategy_state.json"
        empty_state = {
            "active": False,
            "frozen_ratio": None,
            "master_initial_margin": None
        }
        with open(state_file, "w") as f:
            json.dump(empty_state, f, indent=2)
            
        print("[System] Strategy State Manually Reset via API.")
        return {"status": "ok", "message": "Strategy state reset successfully"}
    except Exception as e:
        raise HTTPException(500, f"Failed to reset strategy: {e}")
