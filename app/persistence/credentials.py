from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .windows_secrets import WindowsSecretStore


@dataclass(frozen=True)
class VCenterProfile:
    profile_id: str
    name: str
    host: str
    username: str


class CredentialStore:
    def __init__(self, data_dir: str | Path, *, keyring_backend: Any | None = None, service: str = "vm-clone"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.data_dir / "profiles.json"
        self.keyring = keyring_backend or WindowsSecretStore(self.data_dir, service=service)
        self.service = service

    def list_profiles(self) -> tuple[VCenterProfile, ...]:
        return tuple(
            VCenterProfile(**item)
            for item in self._read_metadata()
        )

    def load(self, profile_id: str) -> VCenterProfile | None:
        return next((profile for profile in self.list_profiles() if profile.profile_id == profile_id), None)

    def save(self, profile: VCenterProfile, password: str) -> None:
        profiles = {item.profile_id: item for item in self.list_profiles()}
        profiles[profile.profile_id] = profile
        self._write_metadata(profiles.values())
        self.keyring.set_password(self.service, profile.profile_id, password)

    def get_password(self, profile: VCenterProfile | str) -> str | None:
        profile_id = profile.profile_id if isinstance(profile, VCenterProfile) else profile
        return self.keyring.get_password(self.service, profile_id)

    def delete(self, profile_id: str) -> None:
        profiles = [item for item in self.list_profiles() if item.profile_id != profile_id]
        self._write_metadata(profiles)
        try:
            self.keyring.delete_password(self.service, profile_id)
        except Exception:
            pass

    def _read_metadata(self) -> list[dict[str, Any]]:
        if not self.metadata_path.exists():
            return []
        try:
            value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write_metadata(self, profiles) -> None:
        payload = [asdict(profile) for profile in profiles]
        self.metadata_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
