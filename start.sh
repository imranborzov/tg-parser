#!/bin/bash
echo "=========================================="
echo "   Starting TG Parser..."
echo "=========================================="
echo ""

if [ ! -d ".venv" ]; then
    echo "[1/3] Creating virtual environment..."
    python3 -m venv .venv
fi

echo "[2/3] Activating environment and installing dependencies..."
source .venv/bin/activate
pip install -r requirements.txt

echo "[3/3] Starting application..."
echo ""
echo "Open in your browser: http://localhost:8000"
echo ""
uvicorn main:app --host 0.0.0.0 --port 8000
