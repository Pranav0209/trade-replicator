import asyncio
from typing import List, Dict, Optional
from datetime import datetime
import math
from kiteconnect import KiteConnect
import config
from db.storage import db
from core.replicator import execute_entry, execute_exit

class MarginOrchestrator:
    def __init__(self, master_user_id: str):
        self.master_id = master_user_id
        self._last_margin: float = 0.0
        self._master_capital: float = 0.0 
        self._active_trades: Dict[str, dict] = {} 
        self._instrument_map: Dict[int, float] = {} # {instrument_token: margin_used}
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
            self._master_capital = live_balance # Use LIVE capital as base for % calculation for accuracy 
            
            self._last_margin = live_balance
            self._initialized = True
            print(f"[Orchestrator] Ready. Baseline Margin: {self._last_margin}")
            
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
            
            # 2. Logic Branch
            if not new_orders:
                # No orders: Just update baseline to absorb MTM changes
                # This ensures we don't treat MTM swing as an "Entry" next time
                self._last_margin = live_balance
                return

            # 3. New Orders Detected
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
                    
                    # Update Instrument Map
                    # Attribute Delta to instruments in new_orders
                    # Simplification: Split equally if multiple orders
                    if len(new_orders) > 0:
                        split_delta = margin_delta / len(new_orders)
                        for order in new_orders:
                            token = order.get("instrument_token")
                            self._instrument_map[token] = self._instrument_map.get(token, 0.0) + split_delta
                    
                    # Store trade state for future exit reference (Legacy/Debug)
                    for order in new_orders:
                        self._active_trades[order['order_id']] = {
                            "margin_used": margin_delta,
                            "allocation_pct": allocation_pct
                        }
                    
                    await execute_entry(
                        master_id=self.master_id, 
                        allocation_pct=allocation_pct, 
                        orders=new_orders,
                        master_pre_trade_margin=self._last_margin
                    )
            
            elif margin_delta < 0:
                # --- EXIT (Margin Released) ---
                released_amount = abs(margin_delta)
                print(f"[Orchestrator] EXIT Triggered. Released: {released_amount}")
                
                # Identify instruments exiting
                # assumption: new_orders contains the exit orders
                exiting_orders = new_orders 
                
                # --- CRITICAL SAFETY: FULL EXIT CHECK ---
                # Margin calculation fails in loss scenarios (Ratio < 100% even if full exit).
                # Force 100% exit if Master is legally flat.
                if await self._master_is_flat(kite):
                    print("[Orchestrator] 🚨 Master is FLAT. Forcing 100% Exit (Ignoring Margin Delta).")
                    await execute_exit(
                        master_id=self.master_id,
                        exit_ratio=1.0,
                        orders=exiting_orders
                    )
                    # Clear map as we are fully flat
                    self._instrument_map.clear()
                    # Update baseline and return early
                    self._last_margin = live_balance
                    return
                # ----------------------------------------
                
                if not exiting_orders:
                    print("[Orchestrator] Exit detected but no orders found? (Maybe delayed update)")
                else:
                    # Logic: We need to calculate Exit Ratio per instrument
                    # If multiple instruments exit, we might need to handle them individually
                    # BUT margin is released in aggregate.
                    # Heuristic: sum up the 'used margin' of all these instruments from our map
                    
                    total_used_for_these_instruments = 0.0
                    relevant_tokens = []
                    
                    for order in exiting_orders:
                        token = order.get("instrument_token")
                        if token:
                            relevant_tokens.append(token)
                            total_used_for_these_instruments += self._instrument_map.get(token, 0.0)
                    
                    if total_used_for_these_instruments > 0:
                        exit_ratio = released_amount / total_used_for_these_instruments
                        # Clamp ratio to 1.0 (100%) to avoid overshoot due to MTM gains/losses affecting release
                        if exit_ratio > 1.0: exit_ratio = 1.0
                        
                        print(f"[Orchestrator] Exit Ratio: {exit_ratio:.2%} (Rel: {released_amount} / Used: {total_used_for_these_instruments})")
                        
                        # Update Map (Reduce used margin)
                        # We reduce proportionally or just reset if ratio is 1?
                        # Reduce by the released amount distributed?
                        # Actually if we exit X%, we should reduce map by X%?
                        # Or reduce by actual released amount? 
                        # Better to reduce by RELEASED amount to keep Delta math consistent?
                        # No, map tracks "Entry Cost". Released amount includes PnL?
                        # Wait. Zerodha Margin:
                        # Entry: 1L used. Map = 1L.
                        # Exit: 1.2L released (Profit). Delta = -1.2L.
                        # Ratio = 1.2L / 1L = 120%. -> Clamped to 100%.
                        # Map becomes 0.
                        # Correct.
                        
                        # What if Loss?
                        # Entry: 1L used.
                        # Exit: 0.8L released (Loss). Delta = -0.8L.
                        # Ratio = 0.8L / 1L = 80%.
                        # Child exits 80%? NO. Child should exit 100% if Master exited 100%.
                        # This is the flaw of "Margin Based Exit" if PnL is involved.
                        
                        # USER SAID: "Children exit only when master exits."
                        # "Exit Ratio = Delta_Exit / Total_Margin_Used"
                        # If PnL makes Delta != Used, Ratio != 100%.
                        
                        # CORRECT APPROACH for 100% Exit:
                        # If Master Order Status is COMPLETE and Quantity matches Position?
                        # But we are polling Orders.
                        # If Master sells 100 qty and had 100 qty.
                        # Only reliable way is Quantity Checks? 
                        # User said "No Quantity Based". "Replication is based on economic exposure".
                        
                        # User's Note: "Exit Ratio = DeltaM / TotalMarginUsed"
                        # "Supports Partial Exits".
                        # If Loss case happens (80% release), we exit 80% of child?
                        # That leaves 20% on child. Master is flat.
                        # This is DANGEROUS.
                        
                        # REFINEMENT:
                        # We must ensure that if Master is FLAT, Child is FLAT.
                        # Margin Delta is good for *Partial* scaling.
                        # But for *Full* exit, we need to know it was full.
                        
                        # However, based on STRICT user spec "Compute exit ratio... Apply to children",
                        # I will implement as requested.
                        # But I will add a safety check: Recalculate based on "Released / (Used - PnL?)" Impossible.
                        # Maybe we rely on the clamp.
                        # If > 1.0 it clamps.
                        # If < 1.0 (Loss), it partial exits.
                        # If Master is flat, but Child has 20% left...
                        # This implies we need a "Cleanup" sweep?
                        
                        # FOR NOW: Implement strict spec.
                        
                        for token in relevant_tokens:
                             # Reduce map
                             # If we have multiple tokens, how do we attribute release?
                             # Proportional to their weight in 'used'?
                             weight = self._instrument_map.get(token, 0) / total_used_for_these_instruments
                             attributed_release = released_amount * weight
                             self._instrument_map[token] = max(0, self._instrument_map.get(token, 0) - attributed_release)

                        await execute_exit(
                            master_id=self.master_id,
                            exit_ratio=exit_ratio,
                            orders=exiting_orders
                        )
                    else:
                        print(f"[Orchestrator] No tracked margin found for tokens {relevant_tokens}. Assuming 100% exit?")
                        await execute_exit(self.master_id, 1.0, exiting_orders)

            # Update baseline
            self._last_margin = live_balance
            
        except Exception as e:
            print(f"[Orchestrator] Tick failed: {e}")
