import os
import json
from pathlib import Path
import asyncio

DATA_DIR = Path("data")
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
ORDERS_FILE = DATA_DIR / "orders.json"

class JSONStore:
    def __init__(self, filepath):
        self.filepath = filepath
        self._lock = asyncio.Lock()
    
    async def find_one(self, query):
        """Find first document matching query."""
        async with self._lock:
            data = await self._read()
            for doc in data:
                match = all(doc.get(k) == v for k, v in query.items())
                if match:
                    return doc
        return None
    
    async def find(self, query):
        """Find all documents matching query."""
        async with self._lock:
            data = await self._read()
            return [doc for doc in data if all(doc.get(k) == v for k, v in query.items())]
    
    async def insert_one(self, doc):
        """Insert a new document."""
        async with self._lock:
            data = await self._read()
            data.append(doc)
            await self._write(data)
        return doc
    
    async def update_one(self, query, update):
        """Update first document matching query."""
        async with self._lock:
            data = await self._read()
            for i, doc in enumerate(data):
                if all(doc.get(k) == v for k, v in query.items()):
                    if "$set" in update:
                        doc.update(update["$set"])
                    elif "$push" in update:
                        for key, val in update["$push"].items():
                            if key not in doc:
                                doc[key] = []
                            doc[key].append(val)
                    data[i] = doc
                    await self._write(data)
                    return doc
        return None
    
    async def _read(self):
        """Read JSON file safely."""
        try:
            if self.filepath.exists():
                with open(self.filepath, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return []
    
    async def _write(self, data):
        """Write JSON file safely."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)

class DB:
    def __init__(self):
        self.accounts = JSONStore(ACCOUNTS_FILE)
        self.orders = JSONStore(ORDERS_FILE)

db = DB()

async def init_db():
    """Initialize data files."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Create empty files if they don't exist
    if not ACCOUNTS_FILE.exists():
        await db.accounts._write([])
    if not ORDERS_FILE.exists():
        await db.orders._write([])
    print("✅ JSON storage initialized")

async def get_db():
    return db
