#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Priveetee/arko-voice-block-challenge.git}"
DEFAULT_INSTALL_ROOT="$(getent passwd "$(id -u)" | cut -d: -f6)"
INSTALL_DIR="${INSTALL_DIR:-${DEFAULT_INSTALL_ROOT}/arko-voice-block-challenge}"

command -v git >/dev/null || { printf '%s\n' 'git est requis.' >&2; exit 1; }
command -v docker >/dev/null || { printf '%s\n' 'Docker est requis.' >&2; exit 1; }
docker compose version >/dev/null || { printf '%s\n' 'Docker Compose est requis.' >&2; exit 1; }
command -v nvidia-smi >/dev/null || { printf '%s\n' 'Le pilote NVIDIA et nvidia-smi sont requis.' >&2; exit 1; }
nvidia-smi -L >/dev/null || { printf '%s\n' 'Aucun GPU NVIDIA utilisable n’a été détecté.' >&2; exit 1; }

if [ -d "${INSTALL_DIR}/.git" ]; then
  git -C "${INSTALL_DIR}" pull --ff-only
else
  if [ -e "${INSTALL_DIR}" ]; then
    printf 'Le dossier existe déjà mais n’est pas un dépôt Git : %s\n' "${INSTALL_DIR}" >&2
    exit 1
  fi
  git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

cd "${INSTALL_DIR}"
docker compose config -q
./provision-model.sh
docker compose up -d --build --remove-orphans

wait_for_health() {
  local container="$1"
  local attempt status
  for attempt in $(seq 1 90); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container}" 2>/dev/null || true)"
    if [ "${status}" = "healthy" ]; then
      return 0
    fi
    if [ "${status}" = "exited" ] || [ "${status}" = "dead" ]; then
      docker logs --tail=80 "${container}" >&2 || true
      return 1
    fi
    sleep 2
  done
  docker logs --tail=80 "${container}" >&2 || true
  return 1
}

wait_for_health speak-no-blocks-asr
wait_for_health minecraft-voice-block
docker compose ps
printf '\nServeur Minecraft: HOST:31877/TCP\nVoice chat: HOST:31878/UDP\n'
