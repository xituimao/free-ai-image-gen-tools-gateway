#!/usr/bin/env bash
# 独立入口脚本，内部委托给 manage.sh
exec "$(dirname "$0")/manage.sh" health "$@"
