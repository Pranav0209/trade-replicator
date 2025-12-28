# PMS Trading Replication Engine

A robust, margin-based trade replication system designed for Zerodha KiteConnect. This system replicates trades from a **Master** account to multiple **Child** accounts based on economic exposure (margin usage) rather than simple quantity multipliers.

## 🚀 Key Features

*   **Margin-Based Replication**:
    *   **Entries**: Triggered by changes in the Master's used margin ($\Delta M$). Child allocation is calculated as `(Delta_Margin / Master_Capital) * Child_Capital`.
    *   **Exits**: Triggered by released margin. Exits are proportional to the Master's exit ratio.
*   **Dynamic Wiring**:
    *   No hardcoded configuration for child accounts.
    *   Simply link an account via the API, and if it's not the Master, it automatically becomes a Child receiver.
*   **Safety First**:
    *   Positions in the Master account are *observed* for reconciliation but never used as replication triggers (avoiding double-counting).
    *   Strict checks to ensure Children only exit when Master exits.
*   **Persisted State**: JSON-based storage for accounts and order logs (`data/`).

## 🛠️ Architecture

*   **`core/orchestrator.py`**: Monitors the Master account. Calculates Margin Deltas ($\Delta M$) and decides *how much* capital to deploy or release.
*   **`core/replicator.py`**: Executes the actual orders on Child accounts. Handles the math to convert "Allocation %" into specific "Quantity" for each child based on their individual capital.
*   **`get_master_positions.py`**: Utility script to peek at the Master's live positions and P&L without affecting the system.

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

3.  **Start the Server**
    ```bash
    python start.py
    ```
    *   Server runs at: `http://127.0.0.1:8000`
    *   API Documentation: `http://127.0.0.1:8000/docs`

## ⚙️ Account Wiring (How to Connect)

The system uses a **Database-First** approach for wiring.

1.  **Link the Master Account**:
    *   Use `POST /accounts/link` with your credentials.
    *   Set `is_master` flag in `data/accounts.json` manually if needed (or via future API update), currently checks `config.py` logic or DB flag.
    *   *Note: Ensure `data/accounts.json` has one account with `"is_master": true`.*

2.  **Link Child Accounts**:
    *   Use `POST /accounts/link` for every child account.
    *   **That's it.** The Replicator automatically queries the database for all valid, non-master accounts and replicates trades to them.

## 🖥️ Usage Guide

### 1. Check Master Status
Run the utility script to see what the master is currently holding.
```bash
python3 get_master_positions.py
```
*Output will show Net Positions (for exits) and Day Positions.*

### 2. Manual Trade Execution (Testing)
You can manually trigger orders via the API (Swagger UI):
*   `POST /trading/place-order`: Places a trade on the Master. The background poller will detect the margin change and replicate it.

### 3. Monitoring
*   Logs are printed to the console (standard output).
*   Order history is saved to `data/orders.json`.

## 🧠 Logic Deep Dive

### Why Margin Based?
Quantity multipliers fail when hedging.
*   *Example*: Master buys 1 lot Future (High Margin) vs Master buys 1 lot Option (Low Margin).
*   A fixed "quantity multiplier" treats both the same.
*   **Margin Based** treats them differently: The Future trade consumes more capital, so it allocates more capital in the child. The Option trade consumes less, allocating less.

### The Algorithm
1.  **Poll Master**: Check `kite.margins()` every `N` seconds.
2.  **Detect Change**:
    *   If `Used Margin` increases $\rightarrow$ **Entry**.
    *   If `Used Margin` decreases $\rightarrow$ **Exit**.
3.  **Calculate Allocation**:
    *   `Alloc_Check = (Old_Margin - New_Margin) / Total_Master_Capital`
4.  **Replicate**:
    *   For each Child: `Target_Margin = Alloc_Check * Child_Available_Capital`.
    *   Convert `Target_Margin` specific instrument Quantity.

## 📂 Directory Structure

```
pms-trading/
├── app.py                  # FastAPI Entry point
├── config.py               # Global constants
├── start.py                # Unified runner
├── core/
│   ├── orchestrator.py     # Master logic (The Brain)
│   └── replicator.py       # Child logic (The Hands)
├── data/                   # JSON Database (accounts, orders)
├── routes/                 # API Routes
└── get_master_positions.py # Utility script
```
