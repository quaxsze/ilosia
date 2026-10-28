#!/bin/sh
set -eu

mkdir -p /tmp/prometheus
rm -f /tmp/prometheus/*.db

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 360 \
  --access-logfile - \
  --error-logfile - \
  --config gunicorn.conf.py
