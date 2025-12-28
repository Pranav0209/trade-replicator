from kiteconnect import KiteConnect
import json
import os

def load_master_credentials():
    accounts_path = os.path.join(os.path.dirname(__file__), "data", "accounts.json")
    with open(accounts_path, "r") as f:
        accounts = json.load(f)
        for acc in accounts:
            if acc.get("is_master"):
                return acc
    return None

master_acc = load_master_credentials()
if not master_acc:
    print("Error: Master account not found in data/accounts.json")
    exit(1)

api_key = master_acc["api_key"]
access_token = master_acc["access_token"]

try:
    print(f"Connecting to Kite with API Key: {api_key}")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    
    print("Fetching Positions...")
    positions = kite.positions()
    
    print("\n=== Net Positions ===")
    net_positions = positions.get("net", [])
    if not net_positions:
        print("No net positions found.")
    else:
        for p in net_positions:
            print(f"{p['tradingsymbol']} ({p['instrument_token']}): {p['quantity']} qty | P&L: {p['pnl']}")

    print("\n=== Day Positions ===")
    day_positions = positions.get("day", [])
    if not day_positions:
        print("No day positions found.")
    else:
        for p in day_positions:
            print(f"{p['tradingsymbol']} ({p['instrument_token']}): {p['quantity']} qty | P&L: {p['pnl']}")
            
except Exception as e:
    print(f"Error fetching positions: {e}")
