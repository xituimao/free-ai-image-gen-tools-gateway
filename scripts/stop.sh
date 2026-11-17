#!/usr/bin/env bash
# Standalone entry script, delegates to manage.sh
exec "$(dirname "$0")/manage.sh" stop "$@"
