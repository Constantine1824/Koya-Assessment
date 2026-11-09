#!/usr/bin/env bash
# Render build step: install dependencies, verify the database is wired up,
# collect static files and run migrations. Runs on every deploy.
set -euo pipefail

echo "==> Installing dependencies"
pip install --upgrade pip
pip install -r requirements.txt

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set." >&2
  echo "Attach a Render PostgreSQL database (render.yaml does this automatically)" >&2
  echo "or set the variable in the dashboard Environment tab." >&2
  exit 1
fi

echo "==> Collecting static files"
python manage.py collectstatic --noinput

echo "==> Applying database migrations"
python manage.py migrate --noinput

echo "==> Django system check (deploy mode; warnings are non-fatal here)"
python manage.py check --deploy || true

echo "==> Build complete"
