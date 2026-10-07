#!/usr/bin/env bash
# Optional standalone scheduler. Do not run this when the worker uses --beat.
set -euo pipefail

: "${CELERY_BROKER_URL:?CELERY_BROKER_URL must be set}"

export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}src"

exec celery --app drugtime.worker:celery_app beat --loglevel="${CELERY_LOG_LEVEL:-INFO}"
