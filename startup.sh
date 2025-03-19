#!/bin/bash
# startup.sh - Script to start the backend server

# Print the banner
echo "
╔═════════════════════════════════════════════╗
║          EYE SPY BACKEND SERVER             ║
║       Face Processing & Identity Search     ║
╚═════════════════════════════════════════════╝
"

# Get the PORT from environment variable or default to 8080
export PORT=${PORT:-8080}
echo "[STARTUP] Starting server on port $PORT..."

# Start the server using gunicorn
# - workers: number of worker processes
# - timeout: request timeout in seconds
# - bind: host:port to bind to
# - backend_server:app - module:variable that contains the Flask application
exec gunicorn --workers=2 --timeout=120 --bind=0.0.0.0:$PORT backend_server:app