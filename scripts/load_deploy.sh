#!/usr/bin/env bash
set -e
ARCHIVE=$1
if [ -z "$ARCHIVE" ]; then echo "Usage: ./load_deploy.sh artifact.zip|strategy2560_xxx.tar.gz"; exit 1; fi
if [[ "$ARCHIVE" == *.zip ]]; then unzip -o "$ARCHIVE"; ARCHIVE=$(ls -t strategy2560_*.tar.gz | head -n 1); fi
echo "Loading $ARCHIVE"
gunzip -c "$ARCHIVE" | docker load
IMG=$(docker images strategy2560 --format "{{.Repository}}:{{.Tag}}" | head -n 1)
docker tag "$IMG" strategy2560:latest
docker compose down --remove-orphans || true
docker compose up -d
docker compose ps
