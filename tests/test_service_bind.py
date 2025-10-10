from app.config import Settings
from app.main import _resolve_service_bind


def test_resolve_service_bind_defaults():
    cfg = Settings()
    host, port = _resolve_service_bind(cfg)
    assert host == "127.0.0.1"
    assert port == 8080


def test_resolve_service_bind_tribute_legacy_defaults():
    cfg = Settings(RUN_TRIBUTE_WEBHOOK=True)
    host, port = _resolve_service_bind(cfg)
    assert host == cfg.WEB_HOST
    assert port == cfg.TRIBUTE_PORT


def test_resolve_service_bind_tribute_port_override():
    cfg = Settings(RUN_TRIBUTE_WEBHOOK=True, TRIBUTE_PORT=9090)
    host, port = _resolve_service_bind(cfg)
    assert host == cfg.WEB_HOST
    assert port == 9090


def test_resolve_service_bind_web_port_override():
    cfg = Settings(WEB_PORT=9091)
    host, port = _resolve_service_bind(cfg)
    assert host == "127.0.0.1"
    assert port == 9091


def test_resolve_service_bind_new_settings_priority():
    cfg = Settings(
        RUN_TRIBUTE_WEBHOOK=True,
        TRIBUTE_PORT=9090,
        SERVICE_HOST="10.0.0.1",
        HEALTH_PORT=8082,
    )
    host, port = _resolve_service_bind(cfg)
    assert host == "10.0.0.1"
    assert port == 8082


def test_resolve_service_bind_web_host_override():
    cfg = Settings(WEB_HOST="192.0.2.10")
    host, port = _resolve_service_bind(cfg)
    assert host == "192.0.2.10"
    assert port == 8080
