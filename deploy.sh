#!/bin/bash
set -e

echo "=== Strategy2560 Docker One-Click Deploy ==="

# 配置区
PROJECT_DIR="/mnt/d/Project/Miller/strategy2560_project_v2_engine"
DEPLOY_TMP="/mnt/d/Project/Miller/.deploy_tmp"
SERVER_USER="user"
SERVER_HOST="192.168.1.30"
SERVER_PASS="P@ssw0rd2025"
REMOTE_DEPLOY="/home/user/deploy_images"
REMOTE_BUILD_DIR=""
REMOTE_IMAGE_BUILT=0
IMAGE_TAR_READY=0
SRC_TAR=""
SUDO="printf '%s\n' '${SERVER_PASS}' | sudo -S"

cd "$PROJECT_DIR"
CURRENT_TAG=$(git rev-parse --short HEAD)
DEPLOY_TAG="deploy-$(date +%Y%m%d-%H%M)-${CURRENT_TAG}"
TAR_NAME="strategy2560_${DEPLOY_TAG}.tar"

echo "[1/7] 检查本地状态..."
git status --short
echo "当前 commit: $CURRENT_TAG"

echo "[2/7] 创建临时目录..."
mkdir -p "$DEPLOY_TMP"

echo "[3/9] 构建镜像 (Windows Docker Desktop)..."
if powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'D:\Project\Miller\strategy2560_project_v2_engine'; docker build -f 'Dockerfile' -t 'strategy2560:${DEPLOY_TAG}' -t 'strategy2560:latest' ."; then
    echo "[4/9] 打包镜像..."
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "docker save 'strategy2560:latest' 'strategy2560:${DEPLOY_TAG}' -o 'D:/Project/Miller/.deploy_tmp/${TAR_NAME}'"
    TAR_SIZE=$(du -h "$DEPLOY_TMP/$TAR_NAME" | cut -f1)
    echo "镜像包大小: $TAR_SIZE"
    IMAGE_TAR_READY=1
else
    echo "本地 Docker 不可用，切换为服务器远端构建..."
    SRC_TAR="strategy2560_src_${DEPLOY_TAG}.tar.gz"
    REMOTE_BUILD_DIR="${REMOTE_DEPLOY}/build_${DEPLOY_TAG}"
    tar \
      --exclude='.git' \
      --exclude='.venv' \
      --exclude='venv' \
      --exclude='__pycache__' \
      --exclude='.pytest_cache' \
      --exclude='.env' \
      --exclude='reports' \
      --exclude='*.tar' \
      --exclude='*.tar.gz' \
      -czf "$DEPLOY_TMP/$SRC_TAR" .
    sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" "mkdir -p '${REMOTE_DEPLOY}' '${REMOTE_BUILD_DIR}'"
    sshpass -p "$SERVER_PASS" scp -o StrictHostKeyChecking=no "$DEPLOY_TMP/$SRC_TAR" "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DEPLOY}/"
    sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
      "tar -xzf '${REMOTE_DEPLOY}/${SRC_TAR}' -C '${REMOTE_BUILD_DIR}' && cd '${REMOTE_BUILD_DIR}' && docker build -f Dockerfile -t 'strategy2560:${DEPLOY_TAG}' -t 'strategy2560:latest' ."
    REMOTE_IMAGE_BUILT=1
fi

echo "[5/9] 准备服务器目录..."
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "mkdir -p '${REMOTE_DEPLOY}' && ${SUDO} mkdir -p /data1/2560/sql /data1/2560/logs /data1/2560/reports"
if [ "$IMAGE_TAR_READY" -eq 1 ]; then
    echo "[5/9] 上传镜像至服务器..."
    sshpass -p "$SERVER_PASS" scp -o StrictHostKeyChecking=no "$DEPLOY_TMP/$TAR_NAME" "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DEPLOY}/"
    if [ $? -ne 0 ]; then
        echo "ERROR: SCP 上传失败!"
        exit 1
    fi
fi

echo "[6/9] 同步 .env 配置至服务器..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: 本地 .env 不存在，无法同步部署配置!"
    exit 1
fi
sshpass -p "$SERVER_PASS" scp -o StrictHostKeyChecking=no "$PROJECT_DIR/.env" "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DEPLOY}/.env_${DEPLOY_TAG}"
sshpass -p "$SERVER_PASS" scp -o StrictHostKeyChecking=no "$PROJECT_DIR/docker-compose.yml" "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DEPLOY}/docker-compose_${DEPLOY_TAG}.yml"
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" "mkdir -p '${REMOTE_DEPLOY}/sql_${DEPLOY_TAG}'"
sshpass -p "$SERVER_PASS" scp -r -o StrictHostKeyChecking=no "$PROJECT_DIR/sql/." "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DEPLOY}/sql_${DEPLOY_TAG}/"
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "${SUDO} install -o '${SERVER_USER}' -g '${SERVER_USER}' -m 600 '${REMOTE_DEPLOY}/.env_${DEPLOY_TAG}' /data1/2560/.env && ${SUDO} cp -f '${REMOTE_DEPLOY}/docker-compose_${DEPLOY_TAG}.yml' /data1/2560/docker-compose.yml && ${SUDO} cp -rf '${REMOTE_DEPLOY}/sql_${DEPLOY_TAG}/.' /data1/2560/sql/"

echo "[6/9] 备份旧容器报告到宿主机..."
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "for container in strategy2560-web strategy2560-worker-data strategy2560-worker-sh60 strategy2560-worker-sh68 strategy2560-worker-sz00 strategy2560-worker-sz30; do if docker ps -a --format '{{.Names}}' | grep -qx \"\${container}\"; then docker cp \"\${container}:/app/reports/.\" /data1/2560/reports/ 2>/dev/null || true; fi; done"

echo "[7/9] 服务器 docker load & compose 更新..."
if [ "$REMOTE_IMAGE_BUILT" -eq 1 ]; then
    sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
      "cd /data1/2560 && docker compose up -d --force-recreate"
else
    sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
      "docker load -i '${REMOTE_DEPLOY}/${TAR_NAME}' && cd /data1/2560 && docker compose up -d --force-recreate"
fi

echo "[8/9] 验证部署..."
echo "等待 10 秒让容器完全启动..."
sleep 10
HEALTH=$(sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" "curl -fsS http://127.0.0.1:8000/health")
echo "健康检查: $HEALTH"

echo "[9/9] 清理僵尸任务..."
CLEANUP=$(sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "curl -s -X POST http://127.0.0.1:8000/api/jobs/admin/cleanup-stuck")
echo "清理结果: $CLEANUP"

IMPORT_CLEANUP=$(sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "curl -s -X POST http://127.0.0.1:8000/api/import/admin/cleanup-stuck")
echo "导入清理结果: $IMPORT_CLEANUP"

echo "[cleanup] 清理临时文件..."
rm -f "$DEPLOY_TMP/$TAR_NAME"
if [ -n "$SRC_TAR" ]; then
    rm -f "$DEPLOY_TMP/$SRC_TAR"
fi
cd "$DEPLOY_TMP" && rmdir 2>/dev/null || true

echo "✅ 部署完成！时间: $(date '+%Y-%m-%d %H:%M:%S')"
