#!/usr/bin/env bash
set -euo pipefail

MODEL_REPO="${WHISPER_MODEL_REPO:-Systran/faster-whisper-large-v3}"
MODEL_REVISION="${WHISPER_MODEL_REVISION:-edaa852ec7e145841d8ffdb056a99866b5f0a478}"
MODEL_CACHE_DIR="${MODEL_CACHE_DIR:-${PWD}/asr-models}"
MODEL_CACHE_NAME="models--${MODEL_REPO//\//--}"
MODEL_SNAPSHOT="${MODEL_CACHE_DIR}/${MODEL_CACHE_NAME}/snapshots/${MODEL_REVISION}"

if [ -s "${MODEL_SNAPSHOT}/model.bin" ] \
    && [ -s "${MODEL_SNAPSHOT}/config.json" ] \
    && [ -s "${MODEL_SNAPSHOT}/tokenizer.json" ]; then
  printf 'Modèle Whisper déjà présent : %s\n' "${MODEL_SNAPSHOT}"
  exit 0
fi

command -v docker >/dev/null || { printf '%s\n' 'Docker est requis.' >&2; exit 1; }
docker compose version >/dev/null || { printf '%s\n' 'Docker Compose est requis.' >&2; exit 1; }

mkdir -p "${MODEL_CACHE_DIR}"
printf 'Téléchargement initial du modèle français (%s, plusieurs Go) ...\n' "${MODEL_REPO}"
docker compose build asr

download_args=(
  --rm
  --no-deps
  -e "HF_HUB_OFFLINE=0"
  -e "TRANSFORMERS_OFFLINE=0"
  -e "MODEL_REPO=${MODEL_REPO}"
  -e "MODEL_REVISION=${MODEL_REVISION}"
  --entrypoint python3
)
if [ -n "${HF_TOKEN:-}" ]; then
  download_args+=( -e "HF_TOKEN=${HF_TOKEN}" )
fi

docker compose run "${download_args[@]}" asr -c '
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id=os.environ["MODEL_REPO"],
    revision=os.environ["MODEL_REVISION"],
    cache_dir="/models",
    token=os.environ.get("HF_TOKEN") or None,
)
'

if [ ! -s "${MODEL_SNAPSHOT}/model.bin" ] \
    || [ ! -s "${MODEL_SNAPSHOT}/config.json" ] \
    || [ ! -s "${MODEL_SNAPSHOT}/tokenizer.json" ]; then
  printf '%s\n' 'Le téléchargement du modèle est incomplet.' >&2
  exit 1
fi

printf 'Modèle prêt : %s\n' "${MODEL_SNAPSHOT}"
