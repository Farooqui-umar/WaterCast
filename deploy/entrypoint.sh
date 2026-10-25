#!/bin/sh
set -e
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "[entrypoint] applying database migrations"
    flask db upgrade
    flask bootstrap-admin
fi
exec "$@"
