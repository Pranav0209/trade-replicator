from fastapi import FastAPI, Request
from datetime import datetime, timezone, timedelta
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from kiteconnect import KiteConnect
import asyncio
from dotenv import load_dotenv
import config

load_dotenv()

from db.storage import init_db, db
from routes import accounts, trading, auth

app = FastAPI(title="PMS Trading Skeleton")

# Setup Templates
templates = Jinja2Templates(directory="templates")

def format_datetime(value):
    if not value: return "-"
    try:
        # Value is naive UTC string from datetime.utcnow().isoformat()
        # e.g. "2023-12-30T10:52:15.123456"
        dt = datetime.fromisoformat(str(value).replace('Z', ''))
        
        # Treat as UTC
        dt = dt.replace(tzinfo=timezone.utc)
        
        # Convert to IST (UTC + 5:30)
        ist = timezone(timedelta(hours=5, minutes=30))
        dt_ist = dt.astimezone(ist)
        
        return dt_ist.strftime("%b %d, %I:%M %p")
    except Exception as e:
        return value

templates.env.filters["datetime"] = format_datetime

def format_inr(number):
    """Format number in Indian Rupee format (e.g. 1,00,000)"""
    if number is None: return "₹0"
    try:
        s = str(int(float(number)))
        if len(s) <= 3:
            return "₹" + s
        
        last_three = s[-3:]
        remaining = s[:-3]
        
        # Add commas every 2 digits for the remaining part (reversed)
        # e.g. 1234 -> 1,234 (handled by last_three but for larger logic)
        # 123456 -> 1,23,456
        
        formatted_remaining = ""
        while len(remaining) > 0:
            if len(remaining) > 2:
                formatted_remaining = "," + remaining[-2:] + formatted_remaining
                remaining = remaining[:-2]
            else:
                formatted_remaining = remaining + formatted_remaining
                remaining = ""
                
        return "₹" + formatted_remaining + "," + last_three
    except:
        return f"₹{number}"

templates.env.filters["inr"] = format_inr

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(auth.router, prefix="/broker", tags=["broker"]) # Alias for Zerodha redirect
app.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
app.include_router(trading.router, prefix="/trading", tags=["trading"])

@app.on_event("startup")
async def startup():
    await init_db()
    
    # Sync Config Accounts to DB
    print("Syncing configured accounts to DB...")
    config_ids = set()
    
    for acc_cfg in config.ACCOUNTS:
        config_ids.add(acc_cfg["user_id"])
        existing = await db.accounts.find_one({"account_id": acc_cfg["user_id"]})
        if not existing:
            # Create new
            doc = {
                "account_id": acc_cfg["user_id"],
                "api_key": acc_cfg["api_key"],
                "api_secret": acc_cfg["api_secret"],
                "is_master": acc_cfg.get("is_master", False),
                "capital": acc_cfg.get("capital", 0),
                "access_token": None,
                "request_token": None,
                "status": "pending",
                "linked_at": None
            }
            await db.accounts.insert_one(doc)
            print(f"Created account: {doc['account_id']}")
        else:
            # Update config fields (keys/secrets might change)
            await db.accounts.update_one(
                {"account_id": acc_cfg["user_id"]},
                {
                    "$set": {
                        "api_key": acc_cfg["api_key"],
                        "api_secret": acc_cfg["api_secret"],
                        "is_master": acc_cfg.get("is_master", False)
                    }
                }
            )
            print(f"Updated account: {acc_cfg['user_id']}")
            
    # Remove stale accounts NOT in config
    all_accounts = await db.accounts.find({})
    for acc in all_accounts:
        if acc["account_id"] not in config_ids:
            print(f"Removing stale account: {acc['account_id']}")
            # We don't have a delete_one method in storage.py yet, let's just filter list
            # But storage.py is append-only JSONStore mostly? 
            # Actually storage.py update_one logic suggests it rewrites file.
            # We need a delete method or we just re-write the whole file.
            
    # Since storage.py is simple, let's just cheat and re-write the file with ONLY config accounts + existing state
    # Actually, simpler: we just tell the user to delete data/accounts.json 
    # OR we implement a delete_one in storage.py.
    
    # Wait, looking at storage.py, it doesn't have delete.
    # Let's reimplement _write with filtered list.
    
    valid_accounts_data = []
    current_data = await db.accounts._read()
    for doc in current_data:
        if doc["account_id"] in config_ids:
            valid_accounts_data.append(doc)
    
    if len(valid_accounts_data) < len(current_data):
        await db.accounts._write(valid_accounts_data)
        print("Cleaned up stale accounts.")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """
    Dashboard to view accounts and login status.
    Uses real-time Kite Profile check to verify token validity.
    """
    accounts_data = await db.accounts.find({})
    
    # Helper: Validate specific account
    async def validate_account(acc):
        if not acc.get("access_token") or acc.get("status") != "connected":
            return False
            
        try:
            # We run the synchronous Kite call in a separate thread to avoid blocking
            loop = asyncio.get_event_loop()
            k = KiteConnect(api_key=acc["api_key"])
            k.set_access_token(acc["access_token"])
            
            # If this succeeds, token is valid
            await loop.run_in_executor(None, k.profile)
            return True
        except Exception as e:
            # Token invalid or network error
            return False

    # Run validations in parallel
    validation_results = await asyncio.gather(*(validate_account(acc) for acc in accounts_data))
    
    # Update statuses for display
    for acc, is_valid in zip(accounts_data, validation_results):
        if acc.get("status") == "connected" and not is_valid:
             acc["status"] = "expired"

    return templates.TemplateResponse("index.html", {
        "request": request,
        "accounts": accounts_data,
        "master_id": config.MASTER_USER_ID
    })

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
