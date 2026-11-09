#!/usr/bin/env bash
# Render start step: production WSGI server. exec keeps signal handling
# (SIGTERM is passed straight to gunicorn) so deploys shut down cleanly.
set -euo pipefail

exec gunicorn clinic.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile - \
  --forwarded-allow-ips "*"
