#!/usr/bin/env bash
set -euo pipefail
umask 077
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
backup_file="${1:?Usage: restore.sh /absolute/backup.dump new_database [--restore]}"
target_database="${2:?Provide a new separate target database}"
[[ "$target_database" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] || { echo 'Invalid target name'; exit 1; }
[[ "$target_database" != postgres && "$target_database" != template0 && "$target_database" != template1 ]] || { echo 'Target must be a new database'; exit 1; }
backup_directory="$(cd -- "$(dirname -- "$backup_file")" && pwd)"
backup_name="$(basename -- "$backup_file")"
[[ "$backup_name" =~ ^danaconnect-[A-Za-z0-9-]+\.dump$ ]] || { echo 'Use an original generated backup filename'; exit 1; }
(cd -- "$backup_directory" && sha256sum --check "$backup_name.sha256")
if [[ "${3:-}" != "--restore" ]]; then
  echo "Checksum matches. Pass --restore to create and restore into $target_database. Live database will not be replaced."
  exit 0
fi
compose=(docker compose --env-file "$project_root/deploy/.env.production" -f "$project_root/compose.prod.yml")
container_path="/tmp/restore-$(python3 -c 'import secrets; print(secrets.token_hex(16))').dump"
cleanup() { "${compose[@]}" exec -T postgres rm -f "$container_path"; }
trap cleanup EXIT
"${compose[@]}" cp "$backup_directory/$backup_name" "postgres:$container_path"
"${compose[@]}" exec -T postgres pg_restore --list "$container_path" > /dev/null
# Verify against the actual running container configuration and refuse its live DB.
"${compose[@]}" exec -T postgres sh -c '[ "$1" != "$POSTGRES_DB" ] || exit 2; createdb --username "$POSTGRES_USER" "$1"' -- "$target_database"
"${compose[@]}" exec -T postgres sh -c 'pg_restore --username "$POSTGRES_USER" --dbname "$1" --no-owner --no-acl --exit-on-error "$2"' -- "$target_database" "$container_path"
echo "Restored into $target_database. If a restore fails the separate target may be partial; inspect it before any promotion."
