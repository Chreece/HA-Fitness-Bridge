DOMAIN = "fitness_bridge"
CONF_SERVER_WS_URL = "server_ws_url"
CONF_BRIDGE_TOKEN = "bridge_token"
CONF_ALLOWED_SERVICE_DOMAINS = "allowed_service_domains"

DEFAULT_SERVER_WS_URL = "ws://127.0.0.1:8732/api/v1/bridge/home-assistant"
DEFAULT_ALLOWED_SERVICE_DOMAINS = (
    "calendar",
    "light",
    "media_player",
    "music_assistant",
    "notify",
    "scene",
    "select",
    "switch",
    "tts",
)

CONF_ENTITY_MIRROR_ENABLED = "entity_mirror_enabled"
DEFAULT_ENTITY_MIRROR_ENABLED = True
