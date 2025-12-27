#!/bin/bash

echo "----------------------------------------"
echo "Starting Docorator Backend..."
echo "Date: $(date)"
echo "PWD:  $(pwd)"
echo "----------------------------------------"

# ---- Install dependencies (CRITICAL) ----
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# ---- Port configuration ----
LISTEN_PORT=${WEBSITES_PORT:-8000}
echo "Listening on port: $LISTEN_PORT"

# ---- Storage ----
export STORAGE_DIR=${STORAGE_DIR:-/home/data}
mkdir -p "$STORAGE_DIR"

# ---- Launch app ----
echo "Launching Uvicorn..."
exec python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port $LISTEN_PORT
