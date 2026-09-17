"""OAuth runs entirely on the HA origin. Fitness never receives HA tokens."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from aiohttp import web, ClientTimeout
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_SERVER_WS_URL, CONF_BRIDGE_TOKEN, DEFAULT_ALLOWED_SERVICE_DOMAINS, CONF_ALLOWED_SERVICE_DOMAINS
from .validation import normalize_ws_url, normalize_bridge_token


class PairingPage(HomeAssistantView):
    url = "/api/fitness_bridge/setup"
    extra_urls = ["/api/fitness_bridge/oauth-callback", "/api/fitness_bridge/oauth-client"]
    name = "api:fitness_bridge:setup"
    requires_auth = False

    async def get(self, request):
        return web.Response(text="""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect Fitness</title>
<style>body{font:16px system-ui;max-width:560px;margin:8vh auto;padding:24px;color:#eaf2f7;background:#101921}button{font:inherit;padding:12px 20px;margin-top:16px;cursor:pointer}p{line-height:1.6;overflow-wrap:anywhere}#status{white-space:pre-wrap}</style>
<h1>Connect Fitness to Home Assistant</h1><p id="status" role="status">Preparing secure setup…</p>
<button id="connect" hidden>Authorize this connection</button>
<script src="/api/fitness_bridge/pairing.js" defer></script></html>""", content_type="text/html", headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
        })


class PairingScript(HomeAssistantView):
    url = "/api/fitness_bridge/pairing.js"
    name = "api:fitness_bridge:pairing_script"
    requires_auth = False

    async def get(self, request):
        content = await asyncio.to_thread(Path(__file__).with_name("pairing.js").read_text, encoding="utf-8")
        return web.Response(text=content, content_type="application/javascript", headers={"Cache-Control": "no-store"})


@websocket_api.websocket_command({"type": "fitness_bridge/pair", vol.Required("fitness_url"): str,
                                  vol.Required("ticket"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def pair(hass, connection, msg):
    # No provider credential fields are accepted by this command.
    origin = str(msg["fitness_url"]).rstrip("/")
    parts = urlsplit(origin)
    if parts.path or parts.query or parts.fragment or parts.scheme not in {"http", "https"}:
        raise ValueError("Invalid Fitness address")
    ws_url = normalize_ws_url(urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc,
                                         "/api/v1/bridge/home-assistant", "", "")))
    ticket = msg["ticket"]
    if not 32 <= len(ticket) <= 128:
        raise ValueError("Invalid pairing ticket")
    entries = hass.config_entries.async_entries(DOMAIN)
    candidates = [e for e in entries if e.data.get(CONF_SERVER_WS_URL) == ws_url]
    if not candidates:
        candidates = [e for e in entries if not e.data.get(CONF_SERVER_WS_URL)]
    if not candidates and len(entries) == 1:
        candidates = entries
    if len(candidates) != 1:
        raise ValueError("Add one Fitness Server Bridge integration using Connect from Fitness, then try again")
    entry = candidates[0]
    session = async_get_clientsession(hass)
    async with session.post(origin + "/fitness-auth/ha/redeem", json={"ticket": ticket},
                            timeout=ClientTimeout(total=20), allow_redirects=False) as response:
        if response.status != 200:
            raise ValueError("Fitness rejected this connection. Sign in again and start a new setup")
        raw = await response.content.read(32769)
        if len(raw) > 32768:
            raise ValueError("Invalid Fitness pairing response")
        result = json.loads(raw)
    if normalize_ws_url(result.get("server_ws_url", "")) != ws_url:
        raise ValueError("Fitness returned a different server address")
    token = normalize_bridge_token(result.get("bridge_token", ""), url=ws_url)
    if not token:
        raise ValueError("Fitness did not issue a bridge credential")
    # Only a Fitness-issued bridge credential is persisted. HA OAuth is browser-only.
    hass.config_entries.async_update_entry(entry, title="Fitness Server", data={**entry.data,
        CONF_SERVER_WS_URL: ws_url, CONF_BRIDGE_TOKEN: token,
        CONF_ALLOWED_SERVICE_DOMAINS: entry.data.get(CONF_ALLOWED_SERVICE_DOMAINS, list(DEFAULT_ALLOWED_SERVICE_DOMAINS)),
    })
    connection.send_result(msg["id"], {"paired": True})


def register_pairing(hass):
    marker = DOMAIN + "_pairing_registered"
    if hass.data.get(marker):
        return
    hass.data[marker] = True
    hass.http.register_view(PairingPage())
    hass.http.register_view(PairingScript())
    websocket_api.async_register_command(hass, pair)
