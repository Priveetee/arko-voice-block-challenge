#!/usr/bin/env bash
set -euo pipefail

REQUEST_FILE=/control/reset-request
WORLD_DIR=/data/voice_block_world
BACKUP_DIR=/backups

if [ -s "${REQUEST_FILE}" ]; then
  seed="$(sed -n 's/^seed=//p' "${REQUEST_FILE}" | head -n 1)"
  case "${seed}" in
    ''|*[!A-Za-z0-9_-]*)
      echo "Invalid reset seed in ${REQUEST_FILE}" >&2
      exit 1
      ;;
  esac

  timestamp="$(date +%Y%m%d-%H%M%S)"
  backup_path="${BACKUP_DIR}/voice_block_world-before-admin-reset-${timestamp}"
  if [ -e "${backup_path}" ]; then
    echo "Reset backup already exists: ${backup_path}" >&2
    exit 1
  fi
  if [ -d "${WORLD_DIR}" ]; then
    mkdir -p "${BACKUP_DIR}"
    mv "${WORLD_DIR}" "${backup_path}"
    echo "Moved previous world to ${backup_path}"
  fi

  if grep -q '^level-seed=' /data/server.properties; then
    sed -i "s/^level-seed=.*/level-seed=${seed}/" /data/server.properties
  else
    printf '\nlevel-seed=%s\n' "${seed}" >> /data/server.properties
  fi
  rm -f "${REQUEST_FILE}"
  echo "Preparing fresh world with seed ${seed}"
fi

exec /image/scripts/start
