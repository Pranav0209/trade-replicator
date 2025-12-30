from fastapi import APIRouter, HTTPException
from datetime import datetime
from kiteconnect import KiteConnect
from db.storage import db
from models.account import LinkAccountIn, AccountResponse, FundsResponse, UpdateAccountIn

router = APIRouter()

@router.post("/link")
async def link_account(body: LinkAccountIn):
    """
    Link a Zerodha account. Stores credentials and generates login URL.
    """
    # Check if already linked
    existing = await db.accounts.find_one({"account_id": body.account_id})
    if existing:
        raise HTTPException(400, f"Account {body.account_id} already linked")
    
    # Create Kite instance to validate credentials
    try:
        kite = KiteConnect(api_key=body.api_key)
        login_url = kite.login_url()
    except Exception as e:
        raise HTTPException(400, f"Invalid Zerodha credentials: {e}")
    
    # Store account
    doc = {
        "account_id": body.account_id,
        "api_key": body.api_key,
        "api_secret": body.api_secret,
        "access_token": None,
        "request_token": None,
        "status": "pending",
        "linked_at": datetime.utcnow().isoformat(),
        "children": []
    }
    result = await db.accounts.insert_one(doc)
    
    return {
        "status": "ok",
        "account_id": body.account_id,
        "login_url": login_url,
        "message": "Complete login at URL above, then use /callback"
    }

@router.get("/callback")
async def broker_callback(request_token: str, account_id: str):
    """
    Exchange request_token for access_token.
    """
    acc = await db.accounts.find_one({"account_id": account_id})
    if not acc:
        raise HTTPException(404, f"Account {account_id} not found")
    
    try:
        kite = KiteConnect(api_key=acc["api_key"])
        data = kite.generate_session(request_token, api_secret=acc["api_secret"])
        
        # Store access token
        await db.accounts.update_one(
            {"account_id": account_id},
            {
                "$set": {
                    "access_token": data.get("access_token"),
                    "request_token": request_token,
                    "status": "connected",
                    "last_updated": datetime.utcnow().isoformat()
                }
            }
        )
        
        return {"status": "success", "account_id": account_id, "user_id": data.get("user_id")}
    except Exception as e:
        raise HTTPException(401, f"Token exchange failed: {e}")

@router.get("/{account_id}")
async def get_account(account_id: str) -> AccountResponse:
    """
    Get account details (without sensitive keys).
    """
    acc = await db.accounts.find_one({"account_id": account_id})
    if not acc:
        raise HTTPException(404, f"Account {account_id} not found")
    
    return AccountResponse(
        account_id=acc["account_id"],
        api_key=acc["api_key"][:5] + "***",  # Masked
        api_secret=acc["api_secret"][:5] + "***",  # Masked
        access_token="***" if acc.get("access_token") else None,
        request_token="***" if acc.get("request_token") else None,
        status=acc["status"],
        linked_at=acc.get("linked_at"),
        children=acc.get("children", []),
        max_capital_usage=acc.get("max_capital_usage", 0.0)
    )

@router.put("/{account_id}")
async def update_account(account_id: str, body: UpdateAccountIn):
    """
    Update account configuration.
    """
    acc = await db.accounts.find_one({"account_id": account_id})
    if not acc:
        raise HTTPException(404, f"Account {account_id} not found")
    
    updates = {}
    if body.max_capital_usage is not None:
        updates["max_capital_usage"] = body.max_capital_usage
        
    if updates:
        await db.accounts.update_one(
            {"account_id": account_id},
            {"$set": updates}
        )
        
    return {"status": "ok", "account_id": account_id}

@router.get("/{account_id}/funds")
async def get_funds(account_id: str) -> FundsResponse:
    """
    Get funds/margins from Zerodha for this account.
    """
    acc = await db.accounts.find_one({"account_id": account_id})
    if not acc:
        raise HTTPException(404, f"Account {account_id} not found")
    
    if acc["status"] != "connected" or not acc.get("access_token"):
        raise HTTPException(400, f"Account {account_id} not connected. Re-authenticate.")
    
    try:
        kite = KiteConnect(api_key=acc["api_key"])
        kite.set_access_token(acc["access_token"])
        
        equity = kite.margins("equity")
        commodity = kite.margins("commodity")
        
        return FundsResponse(
            account_id=account_id,
            equity=equity,
            commodity=commodity
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch funds: {e}")

@router.post("/add-child/{master_id}")
async def add_child_account(master_id: str, child_id: str):
    """
    Link a child account to a master account for replication.
    """
    master = await db.accounts.find_one({"account_id": master_id})
    if not master:
        raise HTTPException(404, f"Master account {master_id} not found")
    
    child = await db.accounts.find_one({"account_id": child_id})
    if not child:
        raise HTTPException(404, f"Child account {child_id} not found")
    
    if child_id in master.get("children", []):
        raise HTTPException(400, f"{child_id} already linked to {master_id}")
    
    await db.accounts.update_one(
        {"account_id": master_id},
        {"$push": {"children": child_id}}
    )
    
    return {"status": "ok", "master_id": master_id, "child_id": child_id}
