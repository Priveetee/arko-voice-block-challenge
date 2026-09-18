#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Priveetee/arko-voice-block-challenge.git}"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/arko-voice-block-challenge}"

command -v git >/dev/null || { printf '%s\n' 'git est requis.' >&2; exit 1; }
command -v docker >/dev/null || { printf '%s\n' 'Docker est requis.' >&2; exit 1; }
docker compose version >/dev/null || { printf '%s\n' 'Docker Compose est requis.' >&2; exit 1; }

if [ -d "${INSTALL_DIR}/.git" ]; then
  git -C "${INSTALL_DIR}" pull --ff-only
else
  git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

cd "${INSTALL_DIR}"
docker compose up -d
docker compose ps
printf '\nServeur Minecraft: HOST:31877/TCP\nVoice chat: HOST:31878/UDP\n'
