#!/bin/sh
# RetailFlow AI — Docker / Azure Container Apps entrypoint
set -e

echo "==> RetailFlow AI starting up..."

# Run DB migrations (idempotent — safe on every restart)
echo "==> Running database migrations..."
alembic upgrade head
echo "==> Migrations complete."

echo "==> Launching API on port 8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
