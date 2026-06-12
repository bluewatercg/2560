from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_progress_runner_public_messages_do_not_use_fast_label():
    text = (PROJECT_ROOT / "scripts/progress_run_now.py").read_text(encoding="utf-8")

    assert "fast ClickHouse 2560 started" not in text
    assert "fast finished" not in text
    assert "[fast]" not in text
    assert "2560 scan started" in text
    assert "2560 scan finished" in text
