from fastapi import APIRouter, HTTPException
from starlette.responses import RedirectResponse
from datetime import datetime
from kiteconnect import KiteConnect
from db.storage import db
import json

router = APIRouter()

@router.get("/login")
async def login(account_id: str):
    """
    Redirect to Zerodha login using user's API key.
    Usage: http://127.0.0.1:8000/auth/login?account_id=CAY950
    """
    # Get user credentials from storage
    user = await db.accounts.find_one({"account_id": account_id})
    if not user:
        raise HTTPException(404, f"User {account_id} not found. Register with /auth/register first.")
    
    try:
        # Generate login URL using user's API key
        kite = KiteConnect(api_key=user["api_key"])
        # Zerodha supports 'state' parameter which is returned in callback
        # We use this to track which user is logging in
        login_url = kite.login_url() + f"&state={account_id}"
        
        # Redirect to Zerodha
        return RedirectResponse(url=login_url)
    except Exception as e:
        raise HTTPException(400, f"Failed to generate login URL: {e}")

@router.get("/callback")
async def callback(request_token: str, account_id: str = None, state: str = None):
    """
    Callback from Zerodha. Exchanges request_token for access_token.
    If account_id/state is missing, tries to match token against all registered accounts.
    """
    effective_account_id = account_id or state
    
    found_user = None
    access_data = None
    
    if effective_account_id:
        # 1. Direct Lookup (Best Case)
        user = await db.accounts.find_one({"account_id": effective_account_id})
        if user:
            try:
                kite = KiteConnect(api_key=user["api_key"])
                access_data = kite.generate_session(request_token, api_secret=user["api_secret"])
                found_user = user
            except Exception as e:
                print(f"Direct auth failed for {effective_account_id}: {e}")
    else:
        # 2. Fallback: Try all potential accounts
        print("Missing state/account_id in callback, searching for matching account...")
        all_accounts = await db.accounts.find({})
        for user in all_accounts:
            try:
                kite = KiteConnect(api_key=user["api_key"])
                access_data = kite.generate_session(request_token, api_secret=user["api_secret"])
                found_user = user
                effective_account_id = user["account_id"]
                print(f"Matched request_token to user: {effective_account_id}")
                break
            except Exception as e:
                # Token invalid for this api_key or other error
                continue
    
    if not found_user or not access_data:
        raise HTTPException(400, "Could not authenticate with any registered account. Invalid token or mismatch.")

    try:    
        # Fetch Live Capital
        kite = KiteConnect(api_key=found_user["api_key"])
        kite.set_access_token(access_data.get("access_token"))
        
        try:
            margins = kite.margins() # Fetch all segments
            equity = margins.get("equity", {})
            available = equity.get("available", {})
            utilised = equity.get("utilised", {})

            opening_balance = float(available.get("opening_balance", 0))
            collateral = float(available.get("collateral", 0))
            used_margin = float(utilised.get("debits", 0))
            
            live_capital = opening_balance + collateral - used_margin
            print(f"Fetched live capital for {effective_account_id}: {live_capital} (Op: {opening_balance} + Col: {collateral} - Used: {used_margin})")
        except Exception as e:
            print(f"Failed to fetch margins for {effective_account_id}: {e}")
            live_capital = found_user.get("capital", 0)

        # Store access token and live capital
        await db.accounts.update_one(
            {"account_id": effective_account_id},
            {
                "$set": {
                    "access_token": access_data.get("access_token"),
                    "request_token": request_token,
                    "status": "connected",
                    "capital": live_capital,
                    "last_updated": datetime.utcnow().isoformat()
                }
            }
        )
        
        return {
            "status": "success",
            "message": f"User {effective_account_id} authenticated successfully!",
            "account_id": effective_account_id
        }
    except Exception as e:
        raise HTTPException(500, f"Database update failed: {e}")

@router.get("/accounts")
async def list_accounts():
    """
    List all registered accounts with their authentication status.
    Usage: http://127.0.0.1:8000/auth/accounts
    """
    accounts = await db.accounts.find({})
    
    return {
        "total": len(accounts),
        "connected": sum(1 for a in accounts if a.get("status") == "connected"),
        "pending": sum(1 for a in accounts if a.get("status") == "pending"),
        "accounts": [
            {
                "user_id": a["account_id"],
                "status": a["status"],
                "linked_at": a.get("linked_at"),
                "has_access_token": bool(a.get("access_token"))
            }
            for a in accounts
        ]
    }

@router.post("/register")
async def register(account_id: str, api_key: str, api_secret: str):
    """
    Pre-register a user with their Zerodha API credentials.
    Usage: POST /auth/register?account_id=CAY950&api_key=xxxxx&api_secret=yyyyy
    """
    # Check if already registered
    existing = await db.accounts.find_one({"account_id": account_id})
    if existing:
        raise HTTPException(400, f"User {account_id} already registered")
    
    try:
        # Validate API key
        kite = KiteConnect(api_key=api_key)
        kite.login_url()  # Validate key works
    except Exception as e:
        raise HTTPException(400, f"Invalid API key: {e}")
    
    # Store user credentials
    doc = {
        "account_id": account_id,
        "api_key": api_key,
        "api_secret": api_secret,
        "access_token": None,
        "request_token": None,
        "status": "pending",
        "linked_at": datetime.utcnow().isoformat(),
        "children": []
    }
    await db.accounts.insert_one(doc)
    
    return {
        "status": "ok",
        "account_id": account_id,
        "next_step": f"Visit: http://127.0.0.1:8000/auth/login?account_id={account_id}"
    }
