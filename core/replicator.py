"""
Trade replication engine.
Replicates master account orders to child accounts proportionally.
"""
from kiteconnect import KiteConnect
from db.storage import db
from datetime import datetime
import uuid
import config
import math # Added for math.floor
import json
import os
from core.strategy_state import state_manager

def get_lot_size(tradingsymbol: str) -> int:
    """
    Get lot size based on trading symbol.
    Logic: NIFTY -> 65 (User Config). Others -> 1 (Default).
    """
    if "NIFTY" in tradingsymbol:
        # Note: Standard Nifty 50 Lot Size is 25, but User requested 65.
        # This handles BANKNIFTY/FINNIFTY overlaps by default unless specific overrides added.
        return 65
    return 1

def aggregate_orders(orders: list) -> list:
    """
    Aggregates split orders into single orders by Instrument + Transaction Type.
    Prevents rounding losses (e.g. 4x 27 lots -> 1x 108 lots).
    """
    if not orders: return []
    
    agg_map = {}
    
    for order in orders:
        # Key: (Instrument Token, Transaction Type, Product, Exchange)
        key = (
            order.get("instrument_token"),
            order.get("transaction_type"),
            order.get("product"),
            order.get("exchange"),
            order.get("tradingsymbol") 
        )
        
        if key not in agg_map:
            # Clone to separate object
            agg_map[key] = order.copy()
        else:
            # Sum Quantity
            agg_map[key]["quantity"] += order.get("quantity", 0)
            
    aggregated = list(agg_map.values())
    
    if len(orders) != len(aggregated):
        print(f"[Replicator] Aggregated {len(orders)} orders into {len(aggregated)} unique positions.")
        
    return aggregated




async def get_master_capital(master_account_id: str) -> float:
    """
    Get usable capital for the master account.
    """
    acc = await db.accounts.find_one({"account_id": master_account_id})
    if not acc:
        raise Exception(f"Master account {master_account_id} not found in DB")
    
    # If not connected, or we want to trust config capital (simpler for now)
    # But ideally, we check margins.
    if acc["status"] == "connected" and acc.get("access_token"):
        try:
            kite = KiteConnect(api_key=acc["api_key"])
            kite.set_access_token(acc["access_token"])
            # User requested using kite.margins() (all segments) instead of kite.margins("equity")
            all_margins = kite.margins()
            equity = all_margins.get("equity", {})
            available_dict = equity.get("available", {})
            utilised_dict = equity.get("utilised", {})
            
            opening_balance = float(available_dict.get("opening_balance", 0))
            collateral = float(available_dict.get("collateral", 0))
            # used_margin = float(utilised_dict.get("debits", 0)) # DO NOT SUBTRACT USED MARGIN
            
            # Use Total Account Size for ratio calculation, not Free Cash
            available = opening_balance + collateral 
            
            print(f"[Capital Debug] Opening: {opening_balance} | Collateral: {collateral}")
            
            if available > 0:
                print(f"Fetched Live Master Capital (Total): {available}")
                return float(available)
            else:
                print("Live capital is 0, falling back to config.")
        except Exception as e:
            print(f"Failed to fetch live master capital: {e}. using fallbacks.")
    
    # Fallback to configured capital
    print(f"Using Configured Capital as fallback for {master_account_id}")
    return acc.get("capital", 5000000.0)


async def execute_entry(master_id: str, allocation_pct: float, orders: list, master_pre_trade_margin: float = None):
    """
    Execute entry orders using FROZEN RATIO strategy logic.
    """
    # Pre-aggregate orders to prevent rounding loss
    orders = aggregate_orders(orders)
    print(f"[Replicator] Signal received with {len(orders)} orders (Aggregated).")
    
    # Pre-fetch Master Live Balance for Strategy Start
    # FIX: Use the Pre-Trade Margin passed from Orchestrator if available
    master_initial_margin = 0.0
    
    if not state_manager.is_active():
        if master_pre_trade_margin and master_pre_trade_margin > 0:
            master_initial_margin = master_pre_trade_margin
            print(f"[Strategy] Using Pre-Trade Snapshot from Orchestrator: {master_initial_margin}")
        else:
             # Fallback if manual call or orchestrator didn't pass it
            try:
                m_acc = await db.accounts.find_one({"account_id": master_id})
                k_m = KiteConnect(api_key=m_acc["api_key"])
                k_m.set_access_token(m_acc["access_token"])
                m_margins = k_m.margins()
                master_initial_margin = float(m_margins["equity"]["available"]["live_balance"])
                print(f"[Strategy] Warning: Fetched Post-Trade Live Bal (Fallback): {master_initial_margin}")
            except Exception as e:
                print(f"[Strategy] Failed to fetch Master Balance: {e}")
                pass
        
        state_manager.set_master_initial_margin(master_initial_margin)

    # Update: Fetch all children, not just configured ones to support dynamic list?
    # Keeping existing Logic: find accounts in DB.
    children_docs = await db.accounts.find({"is_master": False}) # .to_list(None) removed
    
    if not children_docs:
        print("[Replicator] No child accounts found in DB.")
        return

    for child_db in children_docs:
        child_id = child_db["account_id"]
        
        try:
            # --- RATIO LOGIC ---
            ratio = 0.0
            
            if state_manager.is_active():
                # Use FROZEN ratio
                ratio = state_manager.get_frozen_ratio(child_id)
                print(f"[{child_id}] using FROZEN Ratio: {ratio}")
            else:
                # First Leg: Calculate and Freeze
                child_live_balance = 0.0
                if config.DRY_RUN:
                    child_live_balance = child_db.get("capital", 0)
                else:
                    try:
                        k_c = KiteConnect(api_key=child_db["api_key"])
                        k_c.set_access_token(child_db["access_token"])
                        c_margins = k_c.margins()
                        child_live_balance = float(c_margins["equity"]["available"]["live_balance"])
                    except:
                        child_live_balance = child_db.get("capital", 0)
                
                # --- Capital Usage Limit Logic ---
                max_cap = child_db.get("max_capital_usage", 0)
                if max_cap > 0 and child_live_balance > max_cap:
                    print(f"[{child_id}] Capping Capital Usage: {child_live_balance} -> {max_cap}")
                    child_live_balance = max_cap
                # ---------------------------------
                
                master_base = state_manager.get_master_initial_margin()
                if master_base and master_base > 0:
                    ratio = child_live_balance / master_base
                    # Cap Ratio at 1.0 (Safety)
                    if ratio > 1.0:
                        print(f"[{child_id}] Ratio {ratio:.2f} capped to 1.0")
                        ratio = 1.0
                        
                    print(f"[{child_id}] Computed Frozen Ratio: {child_live_balance} / {master_base} = {ratio}")
                else:
                    ratio = 0
            
                # Store in State (Initialize dict if None)
                state_manager.set_frozen_ratio(child_id, ratio)

            # --- PROCESS ORDERS ---
            for order in orders:
                instrument_token = order.get("instrument_token")
                tradingsymbol = order.get("tradingsymbol")
                exchange = order.get("exchange")
                transaction_type = order.get("transaction_type")
                product = order.get("product")
                master_qty = order.get("quantity", 0)
                
                if master_qty == 0: continue

                # Scale Quantity
                LOT_SIZE = get_lot_size(tradingsymbol)
                master_lots = master_qty / LOT_SIZE
                child_lots = math.floor(master_lots * ratio)
                child_quantity = int(child_lots * LOT_SIZE)
                
                debug_info = {
                    "method": "frozen_strategy",
                    "frozen_ratio": ratio,
                    "master_lots": master_lots,
                    "child_lots": child_lots
                }
                
                print(f"[Replicator] {child_id} | Master: {master_lots} lots | Ratio: {ratio:.2f} | Child: {child_lots} lots ({child_quantity} Qty)")

                if child_quantity == 0:
                     print(f"[{child_id}] Calculated 0 lots. Skipping.")
                     continue

                if config.DRY_RUN:
                    print(f"[DRY RUN] {child_id} | Place {transaction_type} {child_quantity} {tradingsymbol}")
                    await db.orders.insert_one({
                        "id": str(uuid.uuid4()),
                        "child_id": child_id,
                        "status": "simulated",
                        "qty": child_quantity,
                        "type": "entry",
                        "instrument_token": instrument_token,
                        "transaction_type": transaction_type,
                        "tradingsymbol": tradingsymbol,
                        "timestamp": datetime.utcnow().isoformat(),
                        "debug_info": debug_info
                    })
                else:
                    # Real Order Placement
                    try:
                        print(f"[{child_id}] Placing ENTRY {transaction_type} {child_quantity} {tradingsymbol}")
                        order_id = kite.place_order(
                            tradingsymbol=tradingsymbol,
                            exchange=exchange,
                            transaction_type=transaction_type,
                            quantity=int(child_quantity),
                            order_type="MARKET",
                            product=product,
                            variety="regular"
                        )
                        print(f"✅ Entry Placed for {child_id}: {order_id}")
                        
                        await db.orders.insert_one({
                            "id": str(uuid.uuid4()),
                            "order_id": order_id,
                            "child_id": child_id,
                            "status": "placed",
                            "qty": child_quantity,
                            "type": "entry",
                            "instrument_token": instrument_token,
                            "transaction_type": transaction_type,
                            "tradingsymbol": tradingsymbol,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                    except Exception as e:
                        print(f"❌ Entry Failed for {child_id}: {e}")
        
        except Exception as e:
            print(f"[{child_id}] Failed: {e}")
    
    # Mark Strategy Active AFTER first processing all children
    if not state_manager.is_active():
        state_manager.activate()

async def execute_exit(master_id: str, exit_ratio: float, orders: list):
    """
    Execute exit orders on children based on Exit Ratio.
    Child_Exit_Qty = floor(Child_Open_Qty * Exit_Ratio)
    
    If orders is empty and exit_ratio == 1.0, forces a "Close All" on tracked positions.
    """
    print(f"[Replicator] Executing EXIT. Ratio: {exit_ratio:.2%}")
    orders = aggregate_orders(orders)
    
    children_docs = await db.accounts.find({"is_master": False})
    
    for child_cfg in children_docs:
        child_id = child_cfg["account_id"]
        
        try:
            # 1. Fetch Open Positions for Child
            pos_map = {}
            
            if config.DRY_RUN:
                # Calculate Net Positions from DB History
                # Filter by Strategy Start Time to prevent drift from old cycles
                query = {"child_id": child_id}
                start_time = state_manager.get_start_time()
                if start_time:
                    query["timestamp"] = {"$gte": start_time}
                
                child_orders = await db.orders.find(query)
                for o in child_orders:
                    # Robustness: Skip orders without token/type
                    if "instrument_token" not in o or "transaction_type" not in o:
                        continue
                        
                    token = o["instrument_token"]
                    qty = o["qty"]
                    # Standardize: BUY is positive, SELL is negative
                    if o["transaction_type"] == "BUY":
                        pos_map[token] = pos_map.get(token, 0) + qty
                    elif o["transaction_type"] == "SELL":
                        pos_map[token] = pos_map.get(token, 0) - qty
                
                print(f"[{child_id}] Calculated Simulated Positions: {pos_map}")
                
            else:
                # Real Positions from Zerodha
                acc = await db.accounts.find_one({"account_id": child_id})
                if not acc or acc["status"] != "connected":
                    print(f"Skipping {child_id}: Not connected")
                    continue
                    
                kite = KiteConnect(api_key=acc["api_key"])
                kite.set_access_token(acc["access_token"])
                
                try:
                    positions = kite.positions()
                    net_positions = positions.get("net", [])
                    pos_map = {p["instrument_token"]: p["quantity"] for p in net_positions if p["quantity"] != 0}
                except Exception as e:
                    print(f"[{child_id}] Failed to fetch positions: {e}")
                    continue

            # 2. Determine Targets
            targets = []
            
            if not orders and exit_ratio >= 0.99:
                 print(f"[{child_id}] CLOSE ALL Triggered (No specific orders provided).")
                 # Create virtual orders for ALL open positions to force close them
                 for token, qty in pos_map.items():
                     if qty != 0:
                         # If Long (qty > 0), we SELL. If Short (qty < 0), we BUY.
                         tx_type = "SELL" if qty > 0 else "BUY"
                         targets.append({
                             "instrument_token": token,
                             "transaction_type": tx_type, 
                             "tradingsymbol": f"TOKEN:{token}", # We might lack symbol if not in map, relying on token
                             "exchange": "NFO", # Assumption! Dangerous if MCX. But usually NFO.
                             "product": "NRML"   # Default to NRML
                         })
                         # Note: For real Close All, we might need to fetch symbol from instrument list if unknown.
                         # But typically orchestrated exits come with orders. This is a failsafe.
            else:
                targets = orders


            # 3. Process Exiting Orders
            for order in targets:
                instrument_token = order.get("instrument_token")
                transaction_type = order.get("transaction_type") # e.g. SELL
                tradingsymbol = order.get("tradingsymbol", f"Tok:{instrument_token}")
                exchange = order.get("exchange", "NFO")
                product = order.get("product", "NRML")
                
                # Check if child has this position
                child_open_qty = pos_map.get(instrument_token, 0)
                
                # Exit implies reducing exposure.
                # If Master Sells, Child should Sell. 
                # (Assuming both are Long, or Master Buys to cover Short).
                # We simply replicate the Transaction Type of the Master's Exit Order.
                
                if child_open_qty == 0:
                    print(f"[{child_id}] No open position for {tradingsymbol}, skipping exit.")
                    continue
                
                # Calculate Qty
                exit_ratio = min(exit_ratio, 1.0) # Safety Clamp
                
                LOT_SIZE = get_lot_size(tradingsymbol)
                
                if exit_ratio >= 0.99:
                     # FULL MATCH: Exit exactly what we have (clean sweep)
                     exit_qty = abs(child_open_qty)
                else:
                     # PARTIAL MATCH: Must be integer multiple of LOT_SIZE
                     raw_qty = abs(child_open_qty) * exit_ratio
                     lots = math.floor(raw_qty / LOT_SIZE)
                     exit_qty = int(lots * LOT_SIZE)
                
                
                if exit_qty == 0:
                    print(f"[{child_id}] Calculated 0 exit query (Ratio {exit_ratio:.2f} * {child_open_qty}), skipping.")
                    continue

                # Cap at open qty just in case
                if exit_qty > abs(child_open_qty):
                    exit_qty = abs(child_open_qty)
                    
                print(f"[{child_id}] Open: {child_open_qty} | Ratio: {exit_ratio:.2f} | Exit Qty: {exit_qty}")

                # FIX: Updates usage tracking to prevent double counting if multiple orders for same token exist
                # Decrement the available quantity for subsequent orders in this loop
                if child_open_qty > 0:
                     pos_map[instrument_token] = max(0, child_open_qty - exit_qty)
                else:
                     # Short position (negative qty), so we add (moving towards 0)
                     # or properly: reduce the magnitude
                     remainder = abs(child_open_qty) - exit_qty
                     pos_map[instrument_token] = -remainder

                if config.DRY_RUN:
                    print(f"[DRY RUN] {child_id} | Place {transaction_type} {exit_qty} {tradingsymbol}")
                    await db.orders.insert_one({
                        "id": str(uuid.uuid4()),
                        "child_id": child_id,
                        "status": "simulated",
                        "qty": exit_qty,
                        "type": "exit",
                        "instrument_token": instrument_token,
                        "transaction_type": transaction_type,
                        "tradingsymbol": tradingsymbol,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                else:
                    # Place Real Order
                    try:
                        order_id = kite.place_order(
                            tradingsymbol=tradingsymbol,
                            exchange=exchange,
                            transaction_type=transaction_type,
                            quantity=exit_qty,
                            order_type="MARKET",
                            product=product,
                            variety="regular"
                        )
                        print(f"✅ Exit Placed for {child_id}: {order_id}")
                    except Exception as e:
                        print(f"❌ Exit Failed for {child_id}: {e}")

        except Exception as e:
            print(f"[{child_id}] Exit processing failed: {e}")

    # --- RESET STATE LOGIC REMOVED ---
    # Strategy Reset is now exclusively handled by the Orchestrator
    # when it confirms the Master Account is completely flat.
    pass

async def get_order_status(account_id: str, order_id: str) -> dict:
    """
    Get status of an order from Zerodha.
    """
    # ... existing implementation ...
    return {} # Placeholder to match signature if needed, mostly unused in polling loop
