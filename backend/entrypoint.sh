#!/bin/bash
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Running seed (если первый запуск)..."
python -m app.seed

echo "Starting cron (бэкапы)..."
cron

echo "Starting nginx (daemon mode)..."
nginx

echo "Starting FastAPI..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
