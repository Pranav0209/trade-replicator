# PMS Trading Replication Engine

A robust, margin-based trade replication system designed for Zerodha KiteConnect. This system replicates trades from a **Master** account to multiple **Child** accounts based on accurate economic exposure (margin usage).

## 🚀 Key Features

- **Single Strategy "Frozen Ratio" Logic**:
  - **Baseline Snapshot**: On the _first leg_ of a new strategy, the system snapshots the available margin of Master (Pre-Trade) and Child.
  - **Frozen Ratio**: Calculates `Ratio = Child_Available / Master_Available` once and **locks it**.
  - **Symmetry**: All subsequent legs (hedges, adjustments) use this exact frozen ratio to ensure perfect hedge symmetry.
  - **Safety**: Ratios are capped at 1.0x to prevent over-leveraging children.
- **Pre-Trade Margin Accuracy**:
  - Uses the Master's margin _before_ the trade execution to calculate ratios, avoiding inflation caused by post-trade margin drops.
- **Dynamic Wiring**:
  - No hardcoded configuration for child accounts. Simply link an account via the API.
  - **Max Capital Usage**: Configure a specific maximum capital limit per child account directly from the UI. The replicator expects this limit when calculating ratios (`min(Available, Max_Cap)`).
- **UI Dashboard**:
  - **Real-Time Wiring**: Monitor connection status and capital usage.
  - **Quick Actions**: Edit capital limits and manage logins per account.
  - **System Controls**: **Reset Strategy** button to manually clear the strategy state at the start of a new trade cycle or to fix state inconsistencies.
  - **Connection Doctor**: Auto-verifies access tokens on page load using live API calls (`kite.profile()`). Alerts with **LOGIN REQ** if disconnected.
  - **Smart Formatting**: Auto-converts timestamps to local time (IST) and currency to Indian numbering format (₹1,00,000).
- **Safety First**:
  - Positions in the Master account are _observed_ but replication is event-driven.
  - **Zero Position Enforcement**: If the Master account is detected as "Flat" (0 open positions), the system calculates a **100% Exit Ratio** for all children immediately, bypassing any margin delta logic. This guarantees no orphan positions in loss scenarios.
- **Precision & Robustness**:
  - **Order Aggregation**: Automatically aggregates simultaneous split orders (e.g., Master splits 100 lots into 4x25) into a single virtual order before calculation. This eliminates rounding losses that occur when replicating small individual orders.
  - **Duplicate Exit Prevention**: Smart tracking of local position state ensures that multiple exit signals for the same instrument do not trigger duplicate exit orders on child accounts.
  - **Safe Lot Sizing**: Currently configured with explicit lot size safeguards (e.g., Nifty @ 65) to ensure integer lot calculations and prevent fractional order errors.
  - **Margin Debounce**: Prevents "False Signals" caused by API race conditions (where Margin updates arrive milliseconds before the Order confirmation). If a significant margin drift is detected without a corresponding order, the system "holds" the baseline until the order arrives.
- **Self-Healing Mechanisms**:
  - **Active State Reconciliation**: If the service is restarted _after_ a manual exit, it detects the anomaly (Active Strategy + Flat Master) and triggers an emergency 100% Exit on children to sync state.
  - **Zombie Map Reconciliation**: On every Exit event, the system cross-checks its internal memory against live Zerodha positions. It automatically purges "Phantom Tokens" (e.g., from previous missed exits), ensuring that the Exit Ratio is calculated against reality.
  - **Clean Slate Initialization**: Restarts wipe the internal instrument map to prevent ghost data from persisting across sessions.
- **Persisted State**:
  - **Strategy State**: The "Frozen Ratio" is saved to disk (`data/strategy_state.json`) immediately upon creation.
  - **Resilience**: The system can be restarted (e.g., over the weekend) and will resume the active strategy with the correct ratio on Monday.
  - **Data**: Accounts and Order Logs are JSON-based and persistent.

## 🛠️ Architecture

- **`polling_service.py`**: The main engine. Runs independently of the UI.
  - **`core/orchestrator.py`**: Monitors the Master account. Calculates Margin Deltas ($\Delta M$) and passes the critical "Pre-Trade Margin" snapshot to the replicator.
  - **`core/replicator.py`**: Executes orders. Manages the global `STRATEGY_STATE` to enforce the Frozen Ratio rule.
- **`start.py`**: The UI / API Server (FastAPI). Used for monitoring and linking accounts.

## 📦 Setup & Installation

1.  **Clone & Install Dependencies**

    ```bash
    cd pms-trading
    pip install -r requirements.txt
    ```

2.  **Environment Configuration**
    Create a `.env` file (optional, mostly for defaults):

    ```ini
    POLL_INTERVAL=5
    MASTER_USER_ID=" "
    ```

3.  **Start the Replication Engine** (Critical)

    ```bash
    python polling_service.py
    ```

4.  **Start the UI / API** (Optional, for monitoring)
    ```bash
    python start.py
    ```
    - Server runs at: `http://127.0.0.1:8000`
    - API Documentation: `http://127.0.0.1:8000/docs`

## ⚙️ Account Wiring (How to Connect)

The system uses a **Database-First** approach for wiring.

1.  **Link the Master Account**:

    - Use `POST /accounts/link` with your credentials.
    - Ensure one account has `"is_master": true` in the DB.

2.  **Link Child Accounts**:
    - Use `POST /accounts/link` for every child account.
    - **That's it.** The Replicator automatically queries the database for all valid, non-master accounts.

## 🎛️ Dashboard Features

The UI (`http://127.0.0.1:8000`) provides real-time control:

- **Configured Capital**: Shows the total available capital or the user-defined limit.
- **Max Cap Usage**: Click "Edit" on any child account to set a hard limit on capital deployment.
  - _Example_: Child has ₹10L but you only want to use ₹5L for replication. Set Max Cap to 500000.
  - The "Frozen Ratio" will be calculated using ₹5L instead of ₹10L.
- **System Controls**:
  - **Reset Strategy State**: Use this button at the start of a new trade cycle (e.g., Wednesday) to clear the previous "Frozen Ratio". This ensures the new cycle starts with a fresh snapshot of your current available capital.

## 🧠 Logic Deep Dive

### 1. The "Frozen Ratio" Rule

To ensure complex multi-leg strategies (like Iron Condors) are replicated with perfect symmetry:

1.  **Start**: The system detects a new trade when no strategy is active.
2.  **Snapshot**: It captures the `Master_Pre_Trade_Margin` (e.g., ₹35L) and `Child_Available` (e.g., ₹10.5L).
3.  **Compute**: `Ratio = 10.5 / 35 = 0.3`.
4.  **Lock**: This ratio (0.3) is stored in memory (`STRATEGY_STATE`).
5.  **Replicate**:
    - Leg 1 (Master 10 lots) -> Child (floor(10 \* 0.3) = 3 lots).
    - Leg 2 (Master 10 lots) -> Child (3 lots) - **No Recalculation**.
6.  **Reset**: When the Master exits 100% of the strategy, the state is cleared, ready for a new snapshot next time.

### 2. Exit Logic

Exits are proportional to the Master's exit.

- If Master exits 50% of their position, Child exits 50% of theirs (Percentage Based).
- **Why?** This ensures the system is self-correcting. If the Child has fewer lots than expected, it still closes the correct _proportion_ of its holdings, preventing "Short" positions or orphaned lots.
- If Master exits 100%, Child exits 100% and the Strategy State resets.

## 🔄 System Flow (Mental Map)

The system operates in two parallel, non-blocking paths:

### 1. The Replication Engine (`polling_service.py`)

This is the core loop that runs independently of the UI.

```
polling_service.py
 └─ fetch master orders + margins
 └─ orchestrator.process_tick()
     ├─ detect ENTRY / EXIT
     ├─ snapshot pre-trade margin
     ├─ verify master flat
     └─ call replicator.execute_entry / execute_exit
         ├─ aggregate orders
         ├─ compute child quantities
         ├─ enforce caps
         ├─ place orders (or DRY_RUN)
         └─ update strategy state (via core/strategy_state.py)
```

### 2. The Management Layer (`start.py`)

This handles the UI and API, completely decoupled from trade execution.

```
start.py (API/UI)
 ├─ auth/login
 ├─ auth/callback
 ├─ accounts config
 └─ dashboard visibility
```

## 📂 Directory Structure

```
pms-trading/
├── polling_service.py      # MAIN REPLICATION ENGINE
├── start.py                # UI / API Server
├── config.py               # Global constants
├── core/
│   ├── orchestrator.py     # Master Monitor & Pre-Trade Snapshotting
│   ├── replicator.py       # Child Execution Logic
│   └── strategy_state.py   # State Persistence & Management (Decoupled)

├── data/                   # JSON Database (accounts, orders)
├── db/                     # DB Connection Layer
│   └── storage.py          # JSONStore Implementation
├── models/                 # Pydantic Models
│   └── account.py          # Account & Request Models
├── routes/                 # API Routes
│   ├── accounts.py         # Account Management
│   ├── auth.py             # Authentication & Token Management
│   └── trading.py          # Manual Trade Execution
├── templates/              # Frontend
│   └── index.html          # Dashboard UI
└── get_master_positions.py # Utility script
```
