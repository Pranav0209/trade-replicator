import asyncio
import os
from datetime import datetime
from kiteconnect import KiteConnect
from db.storage import db, init_db
from core.orchestrator import MarginOrchestrator
import config

# In-memory set to track processed orders
# In production, this should be persistent (Redis/DB) to survive restarts
# But for minimal local usage, memory is fine (or we check DB orders)
seen_orders = set()

async def get_master_client():
    """
    Get authenticated Kite client for master.
    """
    acc = await db.accounts.find_one({"account_id": config.MASTER_USER_ID})
    if not acc or not acc.get("access_token"):
        print(f"Waiting for Master {config.MASTER_USER_ID} to login...")
        return None
        
    try:
        kite = KiteConnect(api_key=acc["api_key"])
        kite.set_access_token(acc["access_token"])
        return kite
    except Exception as e:
        print(f"Error initializing Kite: {e}")
        return None

async def start_polling():
    print(f"Starting Poll Service [Master: {config.MASTER_USER_ID}]")
    print(f"Poll Interval: {config.POLL_INTERVAL}s")
    
    await init_db()
    
    # Initialize Orchestrator
    orchestrator = MarginOrchestrator(config.MASTER_USER_ID)
    try:
        await orchestrator.initialize()
    except Exception as e:
        print(f"Fatal: Orchestrator failed to init: {e}")
        return

    # In-memory monitoring
    # Orchestrator handles state, we just need to detect orders to pass to it
    seen_order_ids = set()
    
    while True:
        try:
            # 1. Fetch Master Orders to detect NEW EVENTS
            acc = await db.accounts.find_one({"account_id": config.MASTER_USER_ID})
            if not acc or acc["status"] != "connected":
                print("Master account not connected. Waiting...")
                await asyncio.sleep(config.POLL_INTERVAL)
                continue
            
            kite = KiteConnect(api_key=acc["api_key"])
            kite.set_access_token(acc["access_token"])
            
            orders = kite.orders()
            
            # Detect new COMPLETED orders
            new_orders = []
            for order in orders:
                if order["status"] == "COMPLETE":
                    if order["order_id"] not in seen_order_ids:
                        new_orders.append(order)
                        seen_order_ids.add(order["order_id"])
            
            # 2. Pass to Orchestrator (Tick)
            # Even if no orders, we tick to update margin MTM
            await orchestrator.process_tick(new_orders)
            
        except Exception as e:
            print(f"Poll Error: {e}")
        
        await asyncio.sleep(config.POLL_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        print("Stopping Poll Service...")
