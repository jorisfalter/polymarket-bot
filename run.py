#!/usr/bin/env python3
"""
Quick start script for Polymarket Insider Detector
"""
import subprocess
import sys
import os

def main():
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║  🔍 POLYMARKET INSIDER DETECTOR                          ║
    ║  Track unusual bets that hint at insider information     ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Check if in virtual environment
    if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("⚠️  Warning: Not running in a virtual environment")
        print("   Consider: python -m venv venv && source venv/bin/activate")
        print()
    
    # Check dependencies
    try:
        import fastapi
        import uvicorn
        import httpx
    except ImportError:
        print("📦 Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    
    print("🚀 Starting server at http://localhost:8000")
    print("   Press Ctrl+C to stop")
    print()
    
    # Start the server
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--reload"
    ])

if __name__ == "__main__":
    main()

