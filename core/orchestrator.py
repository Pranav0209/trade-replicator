import asyncio
from typing import List, Dict, Optional
from datetime import datetime
import math
import time
from kiteconnect import KiteConnect
import config
from db.storage import db
from core.replicator import execute_entry, execute_exit
from core.strategy_state import state_manager

class MarginOrchestrator:
    def __init__(self, master_user_id: str):
        self.master_id = master_user_id
        self._last_margin: float = 0.0
        self._last_entry_ts: float = 0.0
        self._master_capital: float = 0.0 
        self._active_trades: Dict[str, dict] = {} 
        self._master_positions: Dict[int, int] = {} # {instrument_token: quantity}
        self._initialized = False

    async def initialize(self):
        """
        Hydrate initial state. 
        Fetches current margin and sets it as baseline.
        """
        print("[Orchestrator] Initializing...")
        try:
            acc = await db.accounts.find_one({"account_id": self.master_id})
            if not acc or acc["status"] != "connected":
                raise Exception(f"Master account {self.master_id} not connected")

            kite = KiteConnect(api_key=acc["api_key"])
            kite.set_access_token(acc["access_token"])
            
            # Fetch State
            margins = kite.margins()
            equity = margins.get("equity", {})
            available = equity.get("available", {})
            utilised = equity.get("utilised", {})
            
            opening_balance = float(available.get("opening_balance", 0))
            collateral = float(available.get("collateral", 0))
            used_margin = float(utilised.get("debits", 0))
            
            live_balance = opening_balance + collateral - used_margin
            
            # Total capital (for allocation calc) is current 'live_balance' + any 'used'
            # But simpler: use config capital or derived total if no trades active.
            # For now, let's use the DB stored capital as the 'BASE' for % calc.
            self._master_capital = opening_balance + collateral # Use Total Equity (Net Worth) for consistent Ratio
            
            # Reset tracking map since we are establishing a new margin baseline
            self._master_positions.clear()
            # Hydrate positions from live
            try:
                pos = kite.positions()
                net = pos.get("net", [])
                for p in net:
                    if p["quantity"] != 0:
                        self._master_positions[p["instrument_token"]] = p["quantity"]
            except Exception as e:
                print(f"[Orchestrator] Warning: Failed to fetch initial positions: {e}")

            self._last_margin = live_balance
            self._initialized = True
            print(f"[Orchestrator] Ready. Baseline Margin: {self._last_margin} | Positions Tracked: {len(self._master_positions)}")
            
        except Exception as e:
            print(f"[Orchestrator] Initialization failed: {e}")
            raise e

    async def _master_is_flat(self, kite) -> bool:
        """Check if master account has zero open positions."""
        try:
            positions = kite.positions()
            net = positions.get("net", [])
            is_flat = all(p["quantity"] == 0 for p in net)
            if is_flat:
                print("[Orchestrator] Verification: Master is FLAT (0 Open Positions).")
            return is_flat
        except Exception as e:
            print(f"[Orchestrator] Failed to check positions: {e}")
            return False

    # _reconcile_instrument_map Removed (Replaced by Deterministic Position Tracking)

    async def process_tick(self, new_orders: List[dict]):
        """
        Main polling hook.
        1. Fetch current live margin (M_after).
        2. If NO orders -> Update state to drift with market.
        3. If NEW orders -> Calculate Delta -> Trigger Entry/Exit.
        """
        if not self._initialized:
            await self.initialize()
            return

        try:
            # 1. Fetch Current Margin (M_after / M_curr)
            acc = await db.accounts.find_one({"account_id": self.master_id})
            kite = KiteConnect(api_key=acc["api_key"])
            kite.set_access_token(acc["access_token"])
            
            margins = kite.margins()
            equity = margins.get("equity", {})
            available = equity.get("available", {})
            utilised = equity.get("utilised", {})
            
            opening_balance = float(available.get("opening_balance", 0))
            collateral = float(available.get("collateral", 0))
            used_margin = float(utilised.get("debits", 0))
            
            live_balance = opening_balance + collateral - used_margin
            
            # --- FIX: ACTIVE STATE RECONCILIATION (RESTART FIX) ---
            # If Strategy is ACTIVE but Master is FLAT, we missed the exit event.
            # Force Sync Exit.
            if state_manager.is_active():
                # Fix: Grace Period to allow Position API to catch up after Entry
                if time.time() - self._last_entry_ts < 10:
                    print(f"[Orchestrator] Within Entry Grace Period ({int(time.time() - self._last_entry_ts)}s / 15s). Skipping Sync Check.")
                elif await self._master_is_flat(kite):
                     print("[Orchestrator] 🚨 SYNC CHECK: State Active but Master FLAT. Triggering Emergency Exit.")
                     # Only one exit call is needed. The Replicator will calculate and close all positions.
                     await execute_exit(
                        master_id=self.master_id,
                        exit_ratio=1.0,
                        orders=[] # Forces 'Close All' mode in Replicator
                     )
                     self._master_positions.clear()
                     self._last_margin = live_balance
                     print("[Orchestrator] Emergency Exit Complete. Clearing Strategy State.")
                     state_manager.clear()
                     return
            # -----------------------------------------------------

            # 2. Logic Branch
            
            # --- V1 EXIT LOGIC (QUANTITY BASED) ---
            # Poll Positions to detect Exits directly.
            # Rules:
            # 1. Compare Current Qty vs Previous Qty (Per Token).
            # 2. If Abs(Current) < Abs(Previous), it's an Exit.
            # 3. Ratio = (Abs(Prev) - Abs(Curr)) / Abs(Prev).
            # 4. Trigger execute_exit for that token.
            
            current_positions_map = {}
            try:
                positions = kite.positions()
                net_positions = positions.get("net", [])
                for p in net_positions:
                     if p["quantity"] != 0:
                         current_positions_map[p["instrument_token"]] = p["quantity"]
            except Exception as e:
                print(f"[Orchestrator] Failed to fetch positions for Exit Check: {e}")
                # Don't return, allow Entry logic to proceed if needed, but skip exit check this tick
                current_positions_map = self._master_positions # Assume no change to be safe

            # Check for Exits
            # Iterate through KNOWN previous positions
            for token, prev_qty in list(self._master_positions.items()):
                curr_qty = current_positions_map.get(token, 0)
                
                # Rule: Exit if Abs Qty Decreased
                if abs(curr_qty) < abs(prev_qty):
                    # EXIT DETECTED
                    diff = abs(prev_qty) - abs(curr_qty)
                    ratio = diff / abs(prev_qty)
                    
                    # Sanity Clamp
                    if ratio > 1.0: ratio = 1.0
                    if ratio < 0.0: ratio = 0.0 # Should be impossible with logic above

                    print(f"[Orchestrator] EXIT DETECTED on {token}. {prev_qty} -> {curr_qty}. Ratio: {ratio:.2%}")
                    
                    # Construct Synthetic Order for Replicator
                    # If Prev was Long (>0), we SELL. If Prev was Short (<0), we BUY.
                    tx_type = "SELL" if prev_qty > 0 else "BUY"
                    
                    synthetic_order = [{
                        "instrument_token": token,
                        "transaction_type": tx_type,
                        "quantity": diff, # Use diff as qty, though replicator uses ratio
                        "product": "MIS", # Default
                        "exchange": "NFO" # Default
                    }]
                    
                    await execute_exit(
                        master_id=self.master_id,
                        exit_ratio=ratio,
                        orders=synthetic_order
                    )

            # Update State
            self._master_positions = current_positions_map
            
            # --- STRATEGY LIFECYCLE MANAGEMENT ---
            # Strategy Ends ONLY if Master is completely flat (No open positions across ALL tokens).
            # We check _master_positions values (quantities).
            is_master_flat = not any(qty != 0 for qty in self._master_positions.values())
            
            if is_master_flat and state_manager.is_active():
                 print("[Orchestrator] Master is Fully Flat. Ending Strategy Cycle. Clearing State.")
                 state_manager.clear()
            # ---------------------------------------

            if not new_orders:
                # No orders: Just update baseline to absorb MTM changes
                self._last_margin = live_balance
                return

            # 3. New Orders Detected (ENTRY ONLY)
            # Delta = Old (Before) - New (After)
            margin_delta = self._last_margin - live_balance
            print(f"[Orchestrator] Event! Old: {self._last_margin} -> New: {live_balance} | Delta: {margin_delta}")

            if margin_delta > 0:
                # --- ENTRY (Margin Used) ---
                if margin_delta < 500: 
                    print("[Orchestrator] Delta too small, ignoring.")
                else:
                    allocation_pct = margin_delta / self._master_capital
                    print(f"[Orchestrator] ENTRY Triggered. Alloc%: {allocation_pct:.4f}")
                    
                    # Note: We don't update _instrument_map anymore (it's gone).
                    # We strictly rely on Positions for exits.
                    
                    await execute_entry(
                        master_id=self.master_id, 
                        allocation_pct=allocation_pct, 
                        orders=new_orders,
                        master_pre_trade_margin=self._master_capital # Use Total Capital (Equity) for ratio
                    )
                    self._last_entry_ts = time.time()
            
            # REMOVED: elif margin_delta < 0 (Margin Based Exit)

            # Update baseline
            self._last_margin = live_balance
            
        except Exception as e:
            print(f"[Orchestrator] Tick failed: {e}")
