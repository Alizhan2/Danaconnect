#!/usr/bin/env bash
set -euo pipefail
umask 077
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
backup_directory="${1:-$project_root/deploy/backups}"
mkdir -p -- "$backup_directory"
backup_directory="$(cd -- "$backup_directory" && pwd)"
compose=(docker compose --env-file "$project_root/deploy/.env.production" -f "$project_root/compose.prod.yml")
backup_name="danaconnect-$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import secrets; print(secrets.token_hex(4))').dump"
container_path="/tmp/$backup_name"
cleanup() { "${compose[@]}" exec -T postgres rm -f "$container_path"; }
trap cleanup EXIT
"${compose[@]}" exec -T postgres sh -c 'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format custom --file "$1"' -- "$container_path"
"${compose[@]}" cp "postgres:$container_path" "$backup_directory/$backup_name"
(cd -- "$backup_directory" && sha256sum "$backup_name" > "$backup_name.sha256")
echo "Backup created: $backup_directory/$backup_name"
echo 'Copy to encrypted offsite storage. S3 objects and encryption keys need separate backup.'
