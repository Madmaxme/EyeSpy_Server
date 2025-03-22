#!/bin/bash
# dev_env.sh - Development environment setup for EyeSpy Server

# Set environment variables for development
export EYESPY_ENV="development"
export DEBUG="true"
export PORT="8080"
export LOG_LEVEL="DEBUG"

# Database settings
# Your Google Cloud SQL instance connection name
# Format: project-id:region:instance-name
export INSTANCE_CONNECTION_NAME="eyespy-453816:europe-west9:eyespy-db"

# Database credentials (same as used in Cloud Run)
export DB_USER="postgres"
export DB_PASS="Madmaxme"
export DB_NAME="postgres"

# Use a different port for local development (5434 instead of default 5433)
# This prevents conflicts with any existing Cloud SQL Proxy connections
export LOCAL_PROXY_PORT=5434

# If you're using DATABASE_URL format instead:
export DATABASE_URL="postgresql://$DB_USER:$DB_PASS@localhost:$LOCAL_PROXY_PORT/$DB_NAME?host=/cloudsql/$INSTANCE_CONNECTION_NAME"

# API Keys
# Note: Add your actual API keys here for development
export FACECHECK_API_TOKEN=""
export OPENAI_API_KEY=""
export FIRECRAWL_API_KEY=""
export RECORDS_API_KEY=""

# Feature toggles
export ENABLE_RECORD_CHECKING="true"
export ENABLE_BIO_GENERATION="true"
export FACECHECK_TESTING_MODE="true"  # Use testing mode to avoid using credits

# Print setup information
echo "
╔═════════════════════════════════════════════╗
║       EYESPY DEVELOPMENT ENVIRONMENT        ║
║                                             ║
║  Run using: source dev_env.sh               ║
║  Then start: python run.py                  ║
╚═════════════════════════════════════════════╝
"
echo "Development environment variables set."
echo "Cloud SQL Proxy will use port: $LOCAL_PROXY_PORT"
echo ""
echo "DATABASE_URL is set to: $DATABASE_URL"
echo ""
echo "To test the connection, run: python -c \"import db_connector; db_connector.validate_database_connection()\""
echo "To start the server, run: python run.py"

# Detect if script was sourced or executed
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This script must be sourced, not executed:"
    echo "  source dev_env.sh"
    exit 1
fi