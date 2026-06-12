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

cd "$PROJECT_DIR"
CURRENT_TAG=$(git rev-parse --short HEAD)
DEPLOY_TAG="deploy-$(date +%Y%m%d-%H%M)-${CURRENT_TAG}"
TAR_NAME="strategy2560_${DEPLOY_TAG}.tar"

echo "[1/7] 检查本地状态..."
git status --short
echo "当前 commit: $CURRENT_TAG"

echo "[2/7] 创建临时目录..."
mkdir -p "$DEPLOY_TMP"

echo "[3/7] 构建镜像 (Windows Docker Desktop)..."
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'D:\Project\Miller\strategy2560_project_v2_engine'; docker build -f 'Dockerfile' -t 'strategy2560:${DEPLOY_TAG}' -t 'strategy2560:latest' ."
if [ $? -ne 0 ]; then
    echo "ERROR: Docker 构建失败!"
    exit 1
fi

echo "[4/7] 打包镜像..."
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "docker save 'strategy2560:latest' 'strategy2560:${DEPLOY_TAG}' -o 'D:/Project/Miller/.deploy_tmp/${TAR_NAME}'"
TAR_SIZE=$(du -h "$DEPLOY_TMP/$TAR_NAME" | cut -f1)
echo "镜像包大小: $TAR_SIZE"

echo "[5/7] 上传至服务器..."
sshpass -p "$SERVER_PASS" scp -o StrictHostKeyChecking=no "$DEPLOY_TMP/$TAR_NAME" "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DEPLOY}/"
if [ $? -ne 0 ]; then
    echo "ERROR: SCP 上传失败!"
    exit 1
fi

echo "[6/7] 确保并备份服务器报告目录..."
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "printf '%s\n' '${SERVER_PASS}' | sudo -S mkdir -p /data1/2560/reports && if docker ps -a --format '{{.Names}}' | grep -qx strategy2560-web; then docker cp strategy2560-web:/app/reports/. /data1/2560/reports/ 2>/dev/null || true; fi"

echo "[6/7] 服务器 docker load & compose 更新..."
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "docker load -i '${REMOTE_DEPLOY}/${TAR_NAME}' && cd /data1/2560 && docker compose up -d --force-recreate"

echo "[7/7] 验证部署..."
echo "等待 10 秒让容器完全启动..."
sleep 10
HEALTH=$(sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" "curl -fsS http://127.0.0.1:8000/health")
echo "健康检查: $HEALTH"

echo "[8/7] 清理僵尸任务..."
CLEANUP=$(sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "curl -s -X POST http://127.0.0.1:8000/api/jobs/admin/cleanup-stuck")
echo "清理结果: $CLEANUP"

IMPORT_CLEANUP=$(sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
  "curl -s -X POST http://127.0.0.1:8000/api/import/admin/cleanup-stuck")
echo "导入清理结果: $IMPORT_CLEANUP"

echo "[9/7] 清理临时文件..."
rm -f "$DEPLOY_TMP/$TAR_NAME"
cd "$DEPLOY_TMP" && rmdir 2>/dev/null || true

echo "✅ 部署完成！时间: $(date '+%Y-%m-%d %H:%M:%S')"
