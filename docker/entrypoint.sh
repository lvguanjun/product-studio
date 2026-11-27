#!/bin/sh
set -eu

output_dir="${OUTPUT_DIR:-/app/outputs}"
mkdir -p "$output_dir"

if [ "$(id -u)" = "0" ]; then
    app_uid="$(id -u appuser)"
    app_gid="$(id -g appuser)"
    find "$output_dir" \( ! -user "$app_uid" -o ! -group "$app_gid" \) -exec chown "$app_uid:$app_gid" {} +
    chmod u+rwX "$output_dir"
    export HOME="/home/appuser"
    exec setpriv --reuid="$app_uid" --regid="$app_gid" --init-groups -- "$@"
fi

exec "$@"
