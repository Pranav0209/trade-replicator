import asyncio
from unittest.mock import MagicMock, patch
from core.orchestrator import MarginOrchestrator
import config

async def run_margin_test():
    print("=== Running Margin-Based Replication Mock Test ===")
    
    # 1. Setup Mock Orchestrator
    orchestrator = MarginOrchestrator("DVC809") # Use your real ID
    
    # Mock Database capital (Master=50L, Child=10L)
    # We cheat and just set internal state to skip DB calls if possible, 
    # but Orchestrator fetches from DB. Ideally we rely on your real DB since it's local.
    # Assuming DB has DVC809 with ~37L from your previous run.
    
    # 2. Mock KiteConnect
    with patch("core.orchestrator.KiteConnect") as MockKite:
        mock_kite_instance = MockKite.return_value
        
        # --- SCENARIO 1: INITIALIZATION ---
        # Simulate baseline margin of 37L
        mock_kite_instance.margins.return_value = {
            "equity": {
                "available": {"live_balance": 0, "opening_balance": 2000000.0, "collateral": 1700000.0},
                "utilised": {"debits": 0}
            }
        }
        # (20L + 17L - 0) = 37L
        
        print("\n[1] Initializing Orchestrator...")
        await orchestrator.initialize() 
        print(f"Baseline Margin: {orchestrator._last_margin}")
        
        # --- SCENARIO 2: NEW TRADE ENTRY ---
        # Simulate Master buys something, using 1 Lakh Margin
        # New Margin = 36L. Delta = 1L.
        
        # Setup MOCK return values for the next 'process_tick' call
        mock_kite_instance.margins.return_value = {
            "equity": {
                "available": {"live_balance": 0, "opening_balance": 2000000.0, "collateral": 1700000.0},
                "utilised": {"debits": 100000.0} # Used 1L
            }
        }
        
        # New Order Object
        new_order = [{
            "order_id": "TEST_ORDER_1",
            "status": "COMPLETE",
            "transaction_type": "BUY",
            "tradingsymbol": "INFY",
            "quantity": 100,
            "instrument_token": 123456,
            "exchange": "NSE",
            "product": "MIS",
            "order_type": "MARKET",
            "average_price": 1500.0
        }]
        
        print("\n[2] Processing Tick with New Order (1L Margin Used)...")
        
        # Patch execute_entry with AsyncMock
        from unittest.mock import AsyncMock
        with patch("core.orchestrator.execute_entry", new_callable=AsyncMock) as mock_execute:
            await orchestrator.process_tick(new_order)
            
            # VERIFICATION
            # Alloc % should be 1L / 37L = ~2.7%
            expected_alloc = 100000.0 / 3700000.0
            
            if mock_execute.called:
                # Orchestrator calls with kwargs, so check kwargs!
                # await execute_entry(master_id=..., allocation_pct=..., orders=...)
                call_kwargs = mock_execute.call_args.kwargs
                alloc_pct = call_kwargs.get("allocation_pct")
                
                print(f"✅ Replicator Called! Allocation: {alloc_pct:.4%}")
                
                if abs(alloc_pct - expected_alloc) < 0.001:
                    print("✅ Math Check Passed")
                else:
                    print(f"❌ Math Mismatch. Exp: {expected_alloc} vs Got: {alloc_pct}")
            else:
                print("❌ Replicator NOT called.")

        # --- SCENARIO 3: NO ORDERS (MTM DRIFT) ---
        # Simulate market move, margin drops slightly due to MTM but NO new order
        # Should NOT trigger trade
        mock_kite_instance.margins.return_value = {
            "equity": {
                "available": {"live_balance": 0, "opening_balance": 2000000.0, "collateral": 1700000.0},
                "utilised": {"debits": 100500.0} # MTM loss of 500 rs
            }
        }
        
        # --- SCENARIO 4: PARTIAL EXIT (50%) ---
        # Margin Release = 50k (was 1L used). -> 50% ratio.
        # We need mock_kite to now return 50k used margin.
        
        mock_kite_instance.margins.return_value = {
            "equity": {
                "available": {"live_balance": 0, "opening_balance": 2000000.0, "collateral": 1700000.0},
                "utilised": {"debits": 50000.0} # Reduced from 1L to 50k
            }
        }
        
        exit_order = [{
            "order_id": "TEST_ORDER_EXIT_1",
            "status": "COMPLETE",
            # Assuming Exit matches Entry in Instrument Token
            "instrument_token": 123456, 
            "tradingsymbol": "INFY",
            "transaction_type": "SELL",
            "quantity": 50
        }]
        
        print("\n[4] Processing Tick with 50% Exit (50k Margin Released)...")
        # We also need to patch execute_exit now
        with patch("core.orchestrator.execute_exit", new_callable=AsyncMock) as mock_exit:
            await orchestrator.process_tick(exit_order)
            
            if mock_exit.called:
                call_kwargs = mock_exit.call_args.kwargs
                exit_ratio = call_kwargs.get("exit_ratio")
                print(f"✅ Exit Triggered! Ratio: {exit_ratio:.2%}")
                
                # Expected: Wrapped 1L in Map. Released 50k. Ratio = 50/100 = 50%.
                if abs(exit_ratio - 0.50) < 0.05:
                    print(f"✅ Exit Logic Passed. Ratio: {exit_ratio}")
                else:
                    print(f"❌ Ratio Mismatch. Exp: 0.50 vs Got: {exit_ratio}")
            else:
                print("❌ Exit Replicator NOT called.")

if __name__ == "__main__":
    asyncio.run(run_margin_test())
