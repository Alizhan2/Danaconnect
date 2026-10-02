#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$project_root/deploy/readiness.py" --env-file "$project_root/deploy/.env.production"
compose=(docker compose --env-file "$project_root/deploy/.env.production" -f "$project_root/compose.prod.yml")
"${compose[@]}" config -q
if [[ "${1:-}" != "--launch" ]]; then
  echo 'Configuration validated. Pass --launch on the intended Docker host to build and start.'
  exit 0
fi
"${compose[@]}" build api web admin
"${compose[@]}" up -d
"${compose[@]}" ps
