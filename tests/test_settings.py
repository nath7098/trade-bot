from pathlib import Path

import pytest

from tradebot.config import AppConfig, ConfigError, Mode, Secrets, Timeframe, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_default_config_file_is_valid() -> None:
    config = load_config(REPO_ROOT / "config" / "default.yaml")
    assert config.mode is Mode.BACKTEST
    assert config.timeframe is Timeframe.DAY
    assert config.symbols == ("SPY",)


def test_load_custom_config(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "mode: paper\ninitial_capital: 250\nsymbols: [spy, ' qqq ']\n")
    config = load_config(path)
    assert config.mode is Mode.PAPER
    assert config.initial_capital == 250
    assert config.symbols == ("SPY", "QQQ")


def test_live_mode_is_refused(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "mode: live\n")
    with pytest.raises(ConfigError, match="live"):
        load_config(path)


def test_live_mode_is_refused_when_built_directly() -> None:
    with pytest.raises(ValueError, match="live"):
        AppConfig(mode=Mode.LIVE)


@pytest.mark.parametrize(
    "content",
    [
        "initial_capital: 0\n",
        "initial_capital: -10\n",
        "symbols: []\n",
        "symbols: [SPY, spy]\n",
        "timeframe: 1m\n",
        "unknown_key: 1\n",
        "log_level: VERBOSE\n",
    ],
)
def test_invalid_values_are_rejected(tmp_path: Path, content: str) -> None:
    with pytest.raises(ConfigError):
        load_config(write_yaml(tmp_path, content))


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="introuvable"):
        load_config(tmp_path / "absent.yaml")


def test_non_mapping_yaml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(write_yaml(tmp_path, "- a\n- b\n"))


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    assert load_config(write_yaml(tmp_path, "")) == AppConfig()


def test_secrets_come_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # pas de .env local
    monkeypatch.setenv("TRADEBOT_ALPACA_API_KEY", "key-123")
    monkeypatch.setenv("TRADEBOT_ALPACA_API_SECRET", "secret-456")
    secrets = Secrets()
    assert secrets.alpaca_api_key is not None
    assert secrets.alpaca_api_key.get_secret_value() == "key-123"
    # La valeur n'apparaît pas dans la représentation texte.
    assert "secret-456" not in repr(secrets)
    assert "secret-456" not in str(secrets)
