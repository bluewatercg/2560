#!/usr/bin/env bash
set -euo pipefail

LOCAL_ROOT="${1:-/mnt/e/zd_ciccwm/vipdoc}"
REMOTE="${2:-user@192.168.1.30:/data1/2560/zd_ciccwm/vipdoc}"

if [[ ! -d "$LOCAL_ROOT" ]]; then
  echo "Local vipdoc directory not found: $LOCAL_ROOT" >&2
  exit 1
fi

echo "[sync] local:  $LOCAL_ROOT"
echo "[sync] remote: $REMOTE"
echo "[sync] rsync requires SSH access to the server."

rsync -av --delete \
  --include='*/' \
  --include='*.day' \
  --include='*.lc5' \
  --exclude='*' \
  "$LOCAL_ROOT/" "$REMOTE/"

echo "[sync] done"
