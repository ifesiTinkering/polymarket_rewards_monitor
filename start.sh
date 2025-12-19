#!/bin/bash

# Polymarket Rewards Dashboard Startup Script

PORT=8080

# Kill any existing process on the port
echo "Checking for existing processes on port $PORT..."
lsof -ti:$PORT | xargs kill -9 2>/dev/null

# Wait a moment for the port to be released
sleep 1

# Start the server
echo "Starting Polymarket Rewards Monitor on http://localhost:$PORT"
cd "$(dirname "$0")"
python3 rewards_monitor.py $PORT &

# Wait for server to start
sleep 2

# Open browser to the server URL (not a file)
echo "Opening browser..."
/usr/bin/open "http://localhost:$PORT"

echo ""
echo "Dashboard is running at http://localhost:$PORT"
echo "Press Ctrl+C to stop the server"
echo ""

# Wait for the background process
wait
