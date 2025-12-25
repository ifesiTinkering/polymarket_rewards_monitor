#!/bin/bash

# Polymarket Markets Dashboard - Start Script
# Uses the Gamma API to fetch all markets

PORT=8080

echo "Starting Polymarket Markets Dashboard..."

# Kill any existing process on the port
lsof -ti:$PORT | xargs kill -9 2>/dev/null

# Wait a moment
sleep 1

# Start the server in the background
python3 "$(dirname "$0")/markets_dashboard.py" $PORT &

# Wait for server to start
sleep 2

# Open browser
open "http://localhost:$PORT"

echo "Dashboard running at http://localhost:$PORT"
echo "Press Ctrl+C to stop"

# Wait for the background process
wait
