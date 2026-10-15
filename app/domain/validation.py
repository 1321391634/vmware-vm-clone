from __future__ import annotations

import ipaddress
import re


class HostnameValidationError(ValueError):
    pass


_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_hostname(value: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 63 or not _HOSTNAME_RE.fullmatch(value):
        raise HostnameValidationError(
            "hostname 只允许英文字母、数字和连字符，长度不超过 63，且不能以连字符开头或结尾"
        )
    return value


def validate_vm_name(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError("虚拟机名称不能为空")
    if len(value) > 80 or "/" in value or "\\" in value:
        raise ValueError("虚拟机名称长度不能超过 80，且不能包含路径分隔符")
    return value


def parse_ipv4(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(str(value).strip()))
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise ValueError(f"无效的 IPv4 地址: {value}") from exc


def ipv4_range_end(start: str, quantity: int) -> str:
    """Return the inclusive end address for a consecutive allocation."""
    if not isinstance(quantity, int) or quantity < 1:
        raise ValueError("IPv4 分配数量必须是正整数")
    start_address = ipaddress.IPv4Address(str(start).strip())
    end_value = int(start_address) + quantity - 1
    max_value = int(ipaddress.IPv4Address("255.255.255.255"))
    if end_value > max_value:
        raise ValueError("IPv4 分配范围超出 IPv4 地址范围")
    return str(ipaddress.IPv4Address(end_value))


def autofill_ipv4_range(value: str, quantity: int) -> str:
    """Expand one valid start address to the requested clone count.

    Existing ranges, blank input, invalid input, and an address range that
    would overflow IPv4 are returned unchanged so the normal validator can
    provide the user-facing error.
    """
    text = str(value or "").strip()
    if quantity <= 1 or not text or "-" in text:
        return text
    try:
        start = ipaddress.IPv4Address(text)
    except (ipaddress.AddressValueError, ValueError):
        return text
    try:
        end = ipv4_range_end(str(start), quantity)
    except ValueError:
        return text
    return f"{start}-{end}"


def parse_ipv4_range(value: str) -> tuple[str, ...]:
    value = str(value or "").strip()
    if not value:
        raise ValueError("静态 IP 不能为空")
    if "-" not in value:
        return (parse_ipv4(value),)
    parts = [part.strip() for part in value.split("-")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("IPv4 范围格式应为 start-end")
    start = ipaddress.IPv4Address(parts[0])
    end = ipaddress.IPv4Address(parts[1])
    if int(start) > int(end):
        raise ValueError("IPv4 范围起始地址不能大于结束地址")
    return tuple(str(ipaddress.IPv4Address(value)) for value in range(int(start), int(end) + 1))


def validate_optional_ipv4(value: str, label: str) -> str:
    if not str(value or "").strip():
        return ""
    try:
        return parse_ipv4(value)
    except ValueError as exc:
        raise ValueError(f"{label}格式不正确") from exc
