#!/usr/bin/env bash
# Start command của Render Background Worker.
set -euo pipefail

: "${CELERY_BROKER_URL:?CELERY_BROKER_URL must be set}"

export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}src"

exec celery --app drugtime.worker:celery_app worker --beat \
  --without-gossip --without-mingle \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}"
