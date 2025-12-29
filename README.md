# PMS Trading Replication Engine

A robust, margin-based trade replication system designed for Zerodha KiteConnect. This system replicates trades from a **Master** account to multiple **Child** accounts based on accurate economic exposure (margin usage).

## 🚀 Key Features

*   **Single Strategy "Frozen Ratio" Logic**:
    *   **Baseline Snapshot**: On the *first leg* of a new strategy, the system snapshots the available margin of Master (Pre-Trade) and Child.
    *   **Frozen Ratio**: Calculates `Ratio = Child_Available / Master_Available` once and **locks it**.
    *   **Symmetry**: All subsequent legs (hedges, adjustments) use this exact frozen ratio to ensure perfect hedge symmetry.
    *   **Safety**: Ratios are capped at 1.0x to prevent over-leveraging children.
*   **Pre-Trade Margin Accuracy**:
    *   Uses the Master's margin *before* the trade execution to calculate ratios, avoiding inflation caused by post-trade margin drops.
*   **Dynamic Wiring**:
    *   No hardcoded configuration for child accounts. Simply link an account via the API.
*   **Safety First**:
    *   Positions in the Master account are *observed* but replication is event-driven.
    *   Strict checks to ensure Children only exit when Master exits (100% exit = State Reset).
*   **Persisted State**: JSON-based storage for accounts and updated order logs (`data/`).

## 🛠️ Architecture

*   **`polling_service.py`**: The main engine. Runs independently of the UI.
    *   **`core/orchestrator.py`**: Monitors the Master account. Calculates Margin Deltas ($\Delta M$) and passes the critical "Pre-Trade Margin" snapshot to the replicator.
    *   **`core/replicator.py`**: Executes orders. Manages the global `STRATEGY_STATE` to enforce the Frozen Ratio rule.
*   **`start.py`**: The UI / API Server (FastAPI). Used for monitoring and linking accounts.

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
    *   Server runs at: `http://127.0.0.1:8000`
    *   API Documentation: `http://127.0.0.1:8000/docs`

## ⚙️ Account Wiring (How to Connect)

The system uses a **Database-First** approach for wiring.

1.  **Link the Master Account**:
    *   Use `POST /accounts/link` with your credentials.
    *   Ensure one account has `"is_master": true` in the DB.

2.  **Link Child Accounts**:
    *   Use `POST /accounts/link` for every child account.
    *   **That's it.** The Replicator automatically queries the database for all valid, non-master accounts.

## 🧠 Logic Deep Dive

### 1. The "Frozen Ratio" Rule
To ensure complex multi-leg strategies (like Iron Condors) are replicated with perfect symmetry:
1.  **Start**: The system detects a new trade when no strategy is active.
2.  **Snapshot**: It captures the `Master_Pre_Trade_Margin` (e.g., ₹35L) and `Child_Available` (e.g., ₹10.5L).
3.  **Compute**: `Ratio = 10.5 / 35 = 0.3`.
4.  **Lock**: This ratio (0.3) is stored in memory (`STRATEGY_STATE`).
5.  **Replicate**:
    *   Leg 1 (Master 10 lots) -> Child (floor(10 * 0.3) = 3 lots).
    *   Leg 2 (Master 10 lots) -> Child (3 lots) - **No Recalculation**.
6.  **Reset**: When the Master exits 100% of the strategy, the state is cleared, ready for a new snapshot next time.

### 2. Exit Logic
Exits are proportional to the Master's exit.
*   If Master exits 50% of their position, Child exits 50% of theirs.
*   If Master exits 100%, Child exits 100% and the Strategy State resets.

## 📂 Directory Structure

```
pms-trading/
├── polling_service.py      # MAIN REPLICATION ENGINE
├── start.py                # UI / API Server
├── config.py               # Global constants
├── core/
│   ├── orchestrator.py     # Master Monitor & Pre-Trade Snapshotting
│   └── replicator.py       # Child Execution & Strategy State
├── data/                   # JSON Database (accounts, orders)
├── routes/                 # API Routes
└── get_master_positions.py # Utility script
```
