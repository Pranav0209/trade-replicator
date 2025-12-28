import asyncio
import uuid
import config
from core.replicator import replicate_order
from db.storage import init_db

async def run_mock_test():
    """
    Injects a fake 'COMPLETE' order directly into the replicator 
    to verify allocation logic without waiting for real market orders.
    """
    print("Running Mock Replication Test...")
    await init_db()
    
    # Sync Config Accounts to DB for the Test
    print("Syncing configured accounts to DB for test...")
    from db.storage import db
    for acc_cfg in config.ACCOUNTS:
        existing = await db.accounts.find_one({"account_id": acc_cfg["user_id"]})
        if not existing:
            doc = {
                "account_id": acc_cfg["user_id"],
                "api_key": acc_cfg["api_key"],
                "api_secret": acc_cfg["api_secret"],
                "is_master": acc_cfg.get("is_master", False),
                "capital": acc_cfg.get("capital", 0),
                "status": "pending"
            }
            await db.accounts.insert_one(doc)
    
    # Mock Order Details
    mock_order = {
        "instrument_token": 123456,
        "master_quantity": 50,         # Master bought 50
        "price": 100.0,
        "order_type": "MARKET",
        "transaction_type": "BUY",
        "tradingsymbol": "SBIN",
        "product": "MIS",
        "exchange": "NSE"
    }
    
    print(f"Injecting Mock Master Order: {mock_order['transaction_type']} {mock_order['master_quantity']} {mock_order['tradingsymbol']}")
    
    try:
        results = await replicate_order(
            master_account_id=config.MASTER_USER_ID,
            **mock_order
        )
        
        print("\n--- Replication Results ---")
        for res in results:
            print(res)
            
    except Exception as e:
        print(f"Test Failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_mock_test())
