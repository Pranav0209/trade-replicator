from kiteconnect import KiteConnect
import json

# Your DVC809 details from accounts.json
api_key = "dj4ctm58r4o6zyss"
access_token = "fgEXVxa0HA9XzqdhGOyLGjAJKjCoeOO4"

try:
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    
    print("Fetching Margins...")
    margins = kite.margins()
    print(json.dumps(margins, indent=2))
    
    equity_cash = margins.get("equity", {}).get("available", {}).get("cash", 0)
    print(f"\nExtracted Equity Cash: {equity_cash}")
    
except Exception as e:
    print(f"Error: {e}")
