from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_docker_deploy_persists_generated_reports():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    deploy = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert compose.count("./reports:/app/reports") == 6
    assert "/data1/2560/reports" in deploy
    assert "for container in strategy2560-web strategy2560-worker-data strategy2560-worker-sh60 strategy2560-worker-sh68 strategy2560-worker-sz00 strategy2560-worker-sz30" in deploy
    assert 'docker cp \\"\\${container}:/app/reports/.\\" /data1/2560/reports/' in deploy


def test_image_contains_reports_directory_for_unmounted_local_runs():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "mkdir -p /app/logs /app/reports" in dockerfile
