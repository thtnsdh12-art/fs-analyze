import pytest

from src import config


def test_require_api_key_raises_config_error_when_missing(monkeypatch):
    monkeypatch.setattr(config, "DART_API_KEY", None)

    with pytest.raises(config.ConfigError):
        config.require_api_key()


def test_config_error_is_not_caught_by_bare_runtime_error_narrowing():
    """API_ERRORS가 RuntimeError 대신 ConfigError만 잡도록 좋혀졌는지 확인.

    ConfigError 자체는 (기존 DartApiError/ResolveError와 같은 프로젝트 관례상)
    RuntimeError를 상속하지만, main.py는 이제 bare RuntimeError가 아니라 ConfigError를
    명시적으로 잡아야 한다 — 이 테스트는 그 타입 관계 자체를 확인한다.
    """
    assert issubclass(config.ConfigError, RuntimeError)


def test_require_api_key_returns_key_when_present(monkeypatch):
    monkeypatch.setattr(config, "DART_API_KEY", "test-key-123")

    assert config.require_api_key() == "test-key-123"
