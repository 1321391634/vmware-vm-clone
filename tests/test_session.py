from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.vmware.session import VCenterSession  # noqa: E402


def test_vcenter_session_exposes_connection_state():
    session = VCenterSession("vc.example.local", "administrator", "secret")

    assert session.is_connected is False
    session.si = object()
    assert session.is_connected is True


def test_connect_uses_bounded_http_timeouts_and_preferred_api(monkeypatch):
    calls = {}

    def fake_smart_connect(**kwargs):
        calls.update(kwargs)
        return object()

    monkeypatch.setattr("app.vmware.session.SmartConnect", fake_smart_connect)
    session = VCenterSession(
        "vc.example.local",
        "administrator",
        "secret",
        connection_timeout=12,
        connection_pool_timeout=60,
    )

    session.connect()

    assert calls["httpConnectionTimeout"] == 12
    assert calls["connectionPoolTimeout"] == 60
    assert calls["preferredApiVersions"] == ["vim.version.version9"]
