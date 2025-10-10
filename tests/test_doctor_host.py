from app.main import _doctor_host_for_checks


def test_doctor_host_defaults_to_loopback_when_empty() -> None:
    assert _doctor_host_for_checks("") == "127.0.0.1"
    assert _doctor_host_for_checks(None) == "127.0.0.1"


def test_doctor_host_strips_whitespace() -> None:
    assert _doctor_host_for_checks(" 127.0.0.1 \n") == "127.0.0.1"


def test_doctor_host_keeps_regular_hostnames() -> None:
    assert _doctor_host_for_checks("example.test") == "example.test"


def test_doctor_host_wraps_ipv6_literals() -> None:
    assert _doctor_host_for_checks("::1") == "[::1]"
    assert _doctor_host_for_checks("[::1]") == "[::1]"
    assert _doctor_host_for_checks("  [2001:db8::5]  ") == "[2001:db8::5]"


def test_doctor_host_falls_back_for_unspecified_addresses() -> None:
    assert _doctor_host_for_checks("0.0.0.0") == "127.0.0.1"
    assert _doctor_host_for_checks("::") == "127.0.0.1"
    assert _doctor_host_for_checks("[::]") == "127.0.0.1"
