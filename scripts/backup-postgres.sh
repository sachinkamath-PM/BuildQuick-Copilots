#!/usr/bin/env bash
set -euo pipefail

environment_file="${1:-.env.deploy}"
backup_directory="${2:-backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_file="${backup_directory}/buildquick-copilots-${timestamp}.sql.gz"

mkdir -p "${backup_directory}"
docker compose --env-file "${environment_file}" exec -T database \
  sh -c 'pg_dump --clean --if-exists --no-owner --username "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip > "${output_file}"
chmod 600 "${output_file}"
echo "Backup written to ${output_file}"
