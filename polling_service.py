import asyncio
import os
from datetime import datetime
from kiteconnect import KiteConnect
from db.storage import db, init_db
from core.orchestrator import MarginOrchestrator
import config


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
    kite_client = None

    while True:
        try:
            # OPTIMIZATION: Singleton Kite Client
            if kite_client is None:
                acc = await db.accounts.find_one({"account_id": config.MASTER_USER_ID})
                if not acc or acc["status"] != "connected":
                    print("Master account not connected. Waiting...")
                    await asyncio.sleep(config.POLL_INTERVAL)
                    continue
                
                kite_client = KiteConnect(api_key=acc["api_key"])
                kite_client.set_access_token(acc["access_token"])
            
            # 1. Fetch Master Orders to detect NEW EVENTS
            orders = kite_client.orders()
            
            # Detect new COMPLETED orders
            new_orders = []
            for order in orders:
                if order["status"] == "COMPLETE":
                    if order["order_id"] not in seen_order_ids:
                        new_orders.append(order)
                        seen_order_ids.add(order["order_id"])
            
            # 2. Pass to Orchestrator (Tick)
            # Even if no orders,            # 2. Process via Orchestrator
            await orchestrator.process_tick(new_orders)
            
            # Optimization: Prevent memory leak
            if len(seen_order_ids) > 2000:
                seen_order_ids = set(list(seen_order_ids)[-1000:])
            
        except Exception as e:
            print(f"Poll Error: {e}")
            kite_client = None # Reset client to force reconnection/refresh
        
        await asyncio.sleep(config.POLL_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        print("Stopping Poll Service...")
