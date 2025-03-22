#!/bin/bash
# startup.sh - Script to start the backend server with the new controller architecture

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
# - timeout: increased timeout for longer requests (background processing happens in threads)
# - bind: host:port to bind to
# - preload: load the application once first to initialize the controller
# - backend_server:app - module:variable that contains the Flask application
exec gunicorn --workers=2 --timeout=180 --bind=0.0.0.0:$PORT --preload backend_server:app