"""Protocol contracts against small HA API doubles, without requiring HA Core.

Compile the production definitions (with deferred annotations), supplying only
the HA registries/services they use. Live HA/OAuth acceptance is documented too.
"""
import ast
import asyncio
import ipaddress
import logging
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace as NS, ModuleType
from unittest.mock import AsyncMock

import pytest

SOURCE = Path(__file__).parents[1] / "custom_components/fitness_bridge/client.py"


def stack():
    values = {
        "tts.cloud": NS(entity_id="tts.cloud", state="unknown", attributes={"friendly_name":"Cloud speech"}),
        "ai_task.coach": NS(entity_id="ai_task.coach", state="unknown", attributes={"friendly_name":"Coach"}),
        "conversation.admin": NS(entity_id="conversation.admin", state="ok", attributes={}),
        "sensor.polar_steps": NS(entity_id="sensor.polar_steps", state="1200", attributes={"unit_of_measurement":"steps","refresh_token":"do-not-export"}),
        "sensor.polar_login": NS(entity_id="sensor.polar_login", state="secret-string", attributes={}),
        "media_player.gym": NS(entity_id="media_player.gym", state="idle", attributes={"supported_features":512}),
    }
    entities = {key:NS(entity_id=key,disabled_by=None,platform="polar" if key.startswith("sensor") else "cloud",area_id="gym",device_id=None,config_entry_id="polar") for key in values}
    registry = NS(async_get=entities.get)
    hass = NS(states=NS(get=values.get,async_all=lambda domain=None:[v for k,v in values.items() if not domain or k.startswith(domain+".")]),
              config_entries=NS(async_entries=lambda:[NS(entry_id="polar",domain="polar",title="Polar",data={"password":"do-not-export"})]),
              services=NS(async_call=AsyncMock(return_value={"data":"A short workout"}),has_service=lambda *a:True))
    env = {"asyncio":asyncio,"math":math,"ipaddress":ipaddress,"re":re,"_LOGGER":logging.getLogger("test"),
        "DEFAULT_ALLOWED_SERVICE_DOMAINS":("light","tts","media_player","ai_task"),
        "MediaPlayerEntityFeature":NS(PLAY_MEDIA=512),
        "er":NS(async_get=lambda h:registry,async_entries_for_config_entry=lambda r,ident:list(entities.values())),
        "ar":NS(async_get=lambda h:NS(async_list_areas=lambda:[NS(id="gym",name="Gym")])),
        "dr":NS(async_get=lambda h:NS(async_get=lambda x:None)),
    }
    tree = ast.parse(SOURCE.read_text())
    tree.body = [ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0)] + [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
    exec(compile(ast.fix_missing_locations(tree),str(SOURCE),"exec"),env)
    client = env["FitnessBridgeClient"](hass,url="ws://localhost/bridge",token="x"*32)
    client._send_json = AsyncMock()
    return env,hass,client


def test_catalog_supports_cloud_tts_and_unused_ai_without_exposing_secrets():
    env,hass,client = stack()
    catalog = env["_runtime_catalog"](hass)
    assert [x["id"] for x in catalog["tts_entities"]] == ["tts.cloud"]
    assert [x["id"] for x in catalog["ai_entities"]] == ["ai_task.coach"]
    assert [x["id"] for x in catalog["integration_entities"]] == ["sensor.polar_steps"]
    assert "do-not-export" not in str(catalog)


def test_service_domains_and_explicit_ai_entity_are_enforced():
    async def run():
        env,hass,client = stack()
        await client._handle_request({"id":"1","operation":"service/call","domain":"fitness","service":"delete"})
        assert not client._send_json.call_args.args[0]["success"]
        hass.services.async_call.assert_not_awaited()
        await client._handle_request({"id":"2","operation":"ai/generate","entity_id":"conversation.admin","instructions":"Turn off all lights"})
        assert not client._send_json.call_args.args[0]["success"]
        await client._handle_request({"id":"3","operation":"ai/generate","entity_id":"ai_task.coach","instructions":"Plan a workout"})
        assert client._send_json.call_args.args[0]["result"] == {"data":"A short workout"}
        args,kwargs = hass.services.async_call.call_args
        assert args[:2] == ("ai_task","generate_data") and args[2]["entity_id"] == "ai_task.coach"
        assert kwargs["return_response"] is True
        hass.services.async_call.reset_mock()
        client.allowed_service_domains.remove("ai_task")
        await client._handle_request({"id":"4","operation":"ai/generate","entity_id":"ai_task.coach","instructions":"Plan a workout"})
        hass.services.async_call.assert_not_awaited()
    asyncio.run(run())


def test_cloud_sensor_read_exports_only_selected_numeric_values():
    async def run():
        env,hass,client = stack()
        await client._handle_request({"id":"1","operation":"integration/read","entity_ids":["sensor.polar_steps"]})
        result=client._send_json.call_args.args[0]
        assert result["success"] and result["result"]["sensors"][0]["value"] == 1200
        assert "token" not in str(result) and "attributes" not in str(result)
        await client._handle_request({"id":"2","operation":"integration/read","entity_ids":["sensor.polar_login"]})
        assert not client._send_json.call_args.args[0]["success"]
    asyncio.run(run())


def test_media_source_checks_audio_and_keeps_resolved_provider_url_in_ha(monkeypatch):
    async def run():
        env,hass,client = stack()
        provider="media-source://radio_browser"
        def item(ident,name,kind="audio/mpeg",expand=False):
            return NS(media_content_id=ident,title=name,media_content_type=kind,can_play=not expand,can_expand=expand)
        media=NS(async_browse_media=AsyncMock(return_value=NS(title="Radio",children=[item(provider+"/station","Station"),item("media-source://camera/private","Camera","image/jpeg")])),
                 async_resolve_media=AsyncMock(return_value=NS(url="https://provider.invalid/stream?access_token=secret",mime_type="audio/mpeg")))
        components=ModuleType("homeassistant.components");components.media_source=media
        home=ModuleType("homeassistant");home.components=components
        monkeypatch.setitem(sys.modules,"homeassistant",home);monkeypatch.setitem(sys.modules,"homeassistant.components",components)
        client._music_sources=AsyncMock(return_value=[{"id":provider,"name":"Radio"}])
        result=await client._media_operation("media/browse",{"provider":provider,"media_id":provider})
        assert len(result["items"])==1
        result=await client._media_operation("media/play",{"provider":provider,"media_id":provider+"/station","entity_id":"media_player.gym"})
        assert result=={"playing":True}
        assert "secret" not in str(hass.services.async_call.call_args)
        assert hass.services.async_call.call_args.args[2]["media_content_id"]==provider+"/station"
        # A room change must never stop audio selected independently in HA.
        previous = hass.states.get("media_player.gym")
        previous.state = "playing"
        previous.attributes["media_content_id"] = "unrelated-track"
        hass.services.async_call.reset_mock()
        result = await client._media_operation("media/move", {"provider":provider,"media_id":provider+"/station",
            "from_entity_id":"media_player.gym","entity_id":""})
        assert result["reason"] == "previous_playback_not_owned"
        hass.services.async_call.assert_not_awaited()
        previous.attributes["media_content_id"] = "https://provider.invalid/stream?access_token=secret"
        result = await client._media_operation("media/move", {"provider":provider,"media_id":provider+"/station",
            "from_entity_id":"media_player.gym","entity_id":""})
        assert result == {"moved":False,"stopped":True}
        assert hass.services.async_call.call_args.args[:2] == ("media_player","media_stop")
        with pytest.raises(PermissionError):
            await client._media_operation("media/play",{"provider":provider,"media_id":"media-source://camera/private","entity_id":"media_player.gym"})
        media.async_resolve_media.return_value.mime_type="video/mp4"
        with pytest.raises(PermissionError):
            await client._media_operation("media/play",{"provider":provider,"media_id":provider+"/video","entity_id":"media_player.gym"})
    asyncio.run(run())
