from __future__ import annotations

import ssl

from pyVim.connect import Disconnect, SmartConnect


class VCenterSession:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        *,
        connection_timeout: int = 15,
        connection_pool_timeout: int = 60,
    ):
        self.host = host.strip()
        self.username = username
        self.password = password
        self.port = port
        self.connection_timeout = max(1, int(connection_timeout))
        self.connection_pool_timeout = max(1, int(connection_pool_timeout))
        self.preferred_api_versions = ["vim.version.version9"]
        self.si = None

    @property
    def is_connected(self) -> bool:
        return self.si is not None

    @property
    def content(self):
        if self.si is None:
            raise RuntimeError("vCenter 尚未连接")
        return self.si.content

    def connect(self) -> str:
        self.disconnect()
        context = ssl._create_unverified_context()
        self.si = SmartConnect(
            host=self.host,
            user=self.username,
            pwd=self.password,
            port=self.port,
            preferredApiVersions=self.preferred_api_versions,
            httpConnectionTimeout=self.connection_timeout,
            connectionPoolTimeout=self.connection_pool_timeout,
            sslContext=context,
        )
        return f"已连接 {self.host}"

    def disconnect(self) -> None:
        if self.si is not None:
            try:
                Disconnect(self.si)
            finally:
                self.si = None

    def __enter__(self) -> "VCenterSession":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()
