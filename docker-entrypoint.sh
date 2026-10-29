#!/bin/sh
# Startet die Anwendung; Migration und Static-Collection lassen sich bei mehreren
# Replicas über RUN_MIGRATIONS=False bzw. RUN_COLLECTSTATIC=False abschalten.
set -eu

is_enabled() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

if is_enabled "${RUN_MIGRATIONS:-True}"; then
    python manage.py migrate --noinput
fi
if is_enabled "${RUN_COLLECTSTATIC:-True}"; then
    python manage.py collectstatic --noinput
fi

exec gunicorn testgenerator.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 60
