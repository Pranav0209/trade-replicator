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
- **Default Product Type**:
  - All orders are now executed as **NRML (Carry Forward)** by default, aligning with standard swing trading and positional strategies.
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
  - **Strict Logic Separation**:
    - **Entries**: Triggered _only_ by `New Orders` + `Margin Delta` (Economic Exposure).
    - **Exits**: Triggered _only_ by `Position Changes` (Net Quantity Delta).
    - **Zero Position Compliance**: If the Master account is detected as genuinely "Flat" (0 open positions) and no orders are pending, the system triggers a **100% Exit** on children.
- **Precision & Robustness**:
  - **Order Aggregation**: Automatically aggregates simultaneous split orders (e.g., Master splits 100 lots into 4x25) into a single virtual order before calculation. This eliminates rounding losses that occur when replicating small individual orders.
  - **Duplicate Exit Prevention**: Smart tracking of local position state ensures that multiple exit signals for the same instrument do not trigger duplicate exit orders on child accounts.
  - **Dynamic Lot Sizing**: Automatically adapts to different instruments. Defaults to `65` (User Config) for NIFTY indices/options and `1` for stocks/others.
  - **Margin Debounce**: Prevents "False Signals" caused by API race conditions (where Margin updates arrive milliseconds before the Order confirmation). If a significant margin drift is detected without a corresponding order, the system "holds" the baseline until the order arrives.
- **Self-Healing Mechanisms & Robustness**:
  - **Order-Aware Sync Checks**: The emergency "Master Flat" check is now smart enough to pause if `New Orders` are detected in the same poll cycle. This prevents false "Panic Exits" when a new entry is placed but the Position API hasn't updated yet.
  - **Entry Grace Window**: Implements a dedicated "Grace Period" (e.g., 10 seconds) after any new entry to further shield against API latency.
  - **Active State Reconciliation**: Safely handles service restarts. If the strategy is Active but Master is genuinely Flat (after the grace period), it correctly triggers a 100% Exit on children and **clears the strategy state**, preventing infinite exit loops.
  - **Redundant Exit Protection**: The Orchestrator ensures emergency exits are triggered exactly once per event, preventing duplicate order submission.
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

### 2. Exit Logic (V1 Quantity Model)

Exits are triggered by **Position Changes**, not Margin Deltas.

- **Polling**: The system monitors the Master's Net Positions (`kite.positions()`) on every tick.
- **Diff Detection**: `Ratio = (Abs(Prev_Qty) - Abs(Curr_Qty)) / Abs(Prev_Qty)`.
- **Quantization**: Partial exits are rounded down to the nearest `LOT_SIZE` (e.g., 65) to prevent fractional "dust" positions. Full exits (Ratio=1.0) close the exact open quantity.

### 3. Strategy Lifecycle (The "Single Strategy" Rule)

To ensure mathematical correctness for complex strategies (Iron Condors, Adjustments, Rolls):

1.  **Start**: Triggered by the **First Entry** when the Master was previously flat.
2.  **Frozen Ratio**: Calculated ONCE at the start (`Child_Capital / Master_Total_Equity`).
3.  **Persistence**: This ratio is **Locked** and used for ALL subsequent entries, adjustments, and partial exits.
4.  **End**: The strategy state is cleared **ONLY** when the Master Account is **Completely Flat** (0 Open Positions across all instruments).
    - _Crucial_: Exiting one leg fully (e.g., closing the PE side) does NOT end the strategy. The ratio persists for the remaining legs.

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
