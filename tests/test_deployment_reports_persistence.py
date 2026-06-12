from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_docker_deploy_persists_generated_reports():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    deploy = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "./reports:/app/reports" in compose
    assert "/data1/2560/reports" in deploy
    assert "docker cp strategy2560-web:/app/reports/. /data1/2560/reports/" in deploy
