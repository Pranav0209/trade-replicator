#!/usr/bin/env python3
"""
PMS Trading Skeleton - Unified startup script
Installs dependencies and runs the server in one command
"""
import subprocess
import sys
import os

def install_dependencies():
    """Install dependencies from requirements.txt"""
    print("📦 Installing dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    if result.returncode != 0:
        print("❌ Failed to install dependencies")
        sys.exit(1)
    print("✅ Dependencies installed")

def run_server():
    """Start the FastAPI server"""
    print("🚀 Starting PMS Trading server...")
    print("📍 Server: http://127.0.0.1:8000")
    print("📚 API Docs: http://127.0.0.1:8000/docs")
    print("\nPress Ctrl+C to stop\n")
    
    import uvicorn
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )

if __name__ == "__main__":
    install_dependencies()
    run_server()
