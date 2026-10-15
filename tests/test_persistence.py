from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.persistence.credentials import CredentialStore, VCenterProfile  # noqa: E402


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def test_profile_store_persists_connection_without_plaintext_password(tmp_path):
    keyring = FakeKeyring()
    store = CredentialStore(tmp_path, keyring_backend=keyring)
    profile = VCenterProfile(profile_id="profile-1", name="Lab VC", host="10.0.0.10", username="administrator")

    store.save(profile, "super-secret")

    assert store.load("profile-1") == profile
    assert store.get_password(profile) == "super-secret"
    assert "super-secret" not in (tmp_path / "profiles.json").read_text(encoding="utf-8")


def test_delete_profile_removes_metadata_and_secret(tmp_path):
    keyring = FakeKeyring()
    store = CredentialStore(tmp_path, keyring_backend=keyring)
    profile = VCenterProfile(profile_id="profile-1", name="Lab VC", host="10.0.0.10", username="administrator")
    store.save(profile, "super-secret")

    store.delete("profile-1")

    assert store.load("profile-1") is None
    assert store.get_password(profile) is None


def test_default_store_encrypts_password_outside_profile_metadata(tmp_path):
    store = CredentialStore(tmp_path)
    profile = VCenterProfile(profile_id="profile-2", name="Lab VC", host="10.0.0.11", username="administrator")

    store.save(profile, "super-secret")

    assert store.get_password(profile) == "super-secret"
    assert "super-secret" not in (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert "super-secret" not in (tmp_path / "secrets.json").read_text(encoding="utf-8")
