#!/bin/sh
# Lança o app a partir do checkout (Fedora)
exec python3 "$(dirname "$0")/src/main.py" "$@"
