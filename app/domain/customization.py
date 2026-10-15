from __future__ import annotations


_LINUX_GUEST_MARKERS = (
    "linux",
    "rhel",
    "centos",
    "rocky",
    "alma",
    "ubuntu",
    "debian",
    "suse",
    "opensuse",
    "fedora",
    "photon",
    "oraclelinux",
    "amazon",
)


def linux_customization_warning(guest_id: str) -> str | None:
    normalized = str(guest_id or "").strip().casefold()
    if not normalized or "windows" in normalized:
        return None
    if not any(marker in normalized for marker in _LINUX_GUEST_MARKERS):
        return None
    return (
        "Linux 客户机自定义依赖客户机内存在 /usr/bin/cloud-init 或 /usr/bin/perl；"
        "vCenter API 无法在克隆前验证这两个文件。若两者都不存在，VMware Tools 会返回 127，"
        "hostname 和 IP 自定义不会生效。请在模板中安装其中至少一个，并确保 VMware Tools 正常运行。"
    )
