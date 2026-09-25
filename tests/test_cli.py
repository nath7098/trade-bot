import json
import logging
from pathlib import Path

import pytest

from tradebot.cli import main
from tradebot.logging_setup import setup_logging


def test_config_show_hides_secret_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADEBOT_ALPACA_API_SECRET", "top-secret")
    config = tmp_path / "c.yaml"
    config.write_text("mode: paper\n", encoding="utf-8")

    assert main(["--config", str(config), "config", "show"]) == 0
    out = capsys.readouterr().out
    assert '"mode": "paper"' in out
    assert "alpaca_api_secret: défini" in out
    assert "top-secret" not in out


def test_config_show_reports_invalid_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "c.yaml"
    config.write_text("mode: live\n", encoding="utf-8")
    assert main(["--config", str(config), "config", "show"]) == 2
    assert "live" in capsys.readouterr().err


def test_json_log_file(tmp_path: Path) -> None:
    setup_logging(tmp_path, "INFO")
    logging.getLogger("test").info("ordre soumis", extra={"event": {"symbol": "SPY", "qty": 1}})
    for handler in logging.getLogger().handlers:
        handler.flush()

    line = (tmp_path / "tradebot.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["msg"] == "ordre soumis"
    assert record["symbol"] == "SPY"
    assert record["level"] == "INFO"
