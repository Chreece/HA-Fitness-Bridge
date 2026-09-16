"""Pure validation helpers for the HA-Fitness bridge config flow."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

_DOMAIN_RE = re.compile(r"^[a-z0-9_]+$")


def normalize_ws_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        raise ValueError("A ws:// or wss:// Fitness bridge URL is required")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError("Bridge URL must not contain credentials, query parameters or a fragment")
    parsed.port
    if any(char.isspace() for char in raw):
        raise ValueError("Invalid bridge URL")
    host = parsed.hostname.strip().lower()
    if parsed.scheme == "ws" and not _is_local_host(host):
        raise ValueError("Public/non-local Fitness bridge URLs require wss://")
    return raw


def _is_local_host(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_loopback or address.is_private or address.is_link_local)


def normalize_service_domains(value: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        raw_values = value.split(",")
    else:
        raw_values = value
    values = sorted({str(part).strip().lower() for part in raw_values if str(part).strip()})
    if not values or len(values) > 64:
        raise ValueError("At least one and at most 64 service domains are required")
    if any(not _DOMAIN_RE.fullmatch(item) for item in values):
        raise ValueError("Service domains must contain only lowercase letters, digits and underscores")
    if "fitness" in values or "fitness_bridge" in values:
        raise ValueError("Fitness-owned services cannot be delegated through Home Assistant")
    return values


def normalize_bridge_token(value: str, *, url: str) -> str:
    token = str(value or "").strip()
    host = (urlsplit(url).hostname or "").lower()
    remote = not _is_local_host(host)
    if token and len(token) < 24:
        raise ValueError("Bridge token must be at least 24 characters")
    if remote and len(token) < 24:
        raise ValueError("A bridge token is required for non-local Fitness Server connections")
    if len(token) > 512:
        raise ValueError("Bridge token is too long")
    return token
