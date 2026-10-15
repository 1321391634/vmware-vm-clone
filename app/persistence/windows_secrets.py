from __future__ import annotations

import base64
import ctypes
import os
from ctypes import POINTER, Structure, byref, c_ubyte, c_uint32, cast, create_string_buffer, string_at


class _DataBlob(Structure):
    _fields_ = [("cbData", c_uint32), ("pbData", POINTER(c_ubyte))]


def _make_blob(value: bytes) -> tuple[_DataBlob, object]:
    buffer = create_string_buffer(value)
    return _DataBlob(len(value), cast(buffer, POINTER(c_ubyte))), buffer


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI 仅支持 Windows")


def protect(value: str) -> str:
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, source_buffer = _make_blob(value.encode("utf-8"))
    result = _DataBlob()
    if not crypt32.CryptProtectData(byref(source), None, None, None, None, 0, byref(result)):
        raise ctypes.WinError()
    try:
        encrypted = string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def unprotect(value: str) -> str:
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    encrypted = base64.b64decode(value.encode("ascii"))
    source, source_buffer = _make_blob(encrypted)
    result = _DataBlob()
    if not crypt32.CryptUnprotectData(byref(source), None, None, None, None, 0, byref(result)):
        raise ctypes.WinError()
    try:
        plain = string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
    return plain.decode("utf-8")


class WindowsSecretStore:
    def __init__(self, data_dir, *, service: str = "vm-clone"):
        self.path = os.fspath(data_dir) + os.sep + "secrets.json"
        self.service = service

    def _read(self) -> dict[str, str]:
        import json
        from pathlib import Path

        try:
            value = json.loads(Path(self.path).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, values: dict[str, str]) -> None:
        import json
        from pathlib import Path

        Path(self.path).write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_password(self, service: str, username: str, password: str) -> None:
        values = self._read()
        values[f"{service}:{username}"] = protect(password)
        self._write(values)

    def get_password(self, service: str, username: str) -> str | None:
        value = self._read().get(f"{service}:{username}")
        return unprotect(value) if value else None

    def delete_password(self, service: str, username: str) -> None:
        values = self._read()
        values.pop(f"{service}:{username}", None)
        self._write(values)

