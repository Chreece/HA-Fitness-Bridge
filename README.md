# HA-Fitness Bridge 0.31.0a1

Optional Home Assistant integration for standalone Fitness Server 0.80.0a31.
Fitness accounts, workouts, storage, device ingestion and native features stay independent of Home Assistant.

## Test installation

Run `bash tools/install_bridge_a31.sh /config` on the HA host, passing the actual Home Assistant configuration directory. The self-contained installer creates a backup of only the existing `custom_components/fitness_bridge` directory, installs this matched bridge, and prints the backup location. Restart Home Assistant afterward. It does not modify the legacy `fitness` integration.

In Home Assistant, add **Fitness Server Bridge** and choose **Connect from Fitness (OAuth)**. In Fitness Admin → Settings → Fitness features → Home Assistant bridge, open **Connect with Home Assistant**, enter the HA and Fitness origins, then sign in as an HA administrator in the popup. Existing bridge entries can be reconnected. Fitness must be reachable from HA at the supplied address.

The OAuth callback and temporary HA tokens stay on the HA origin and the grant is revoked after pairing. HA stores only the Fitness-issued credential for its outbound bridge connection; Fitness stores its hash. The admin browser does not have to stay open. A five-minute setup ticket is single-use and bound to a still-authorized Fitness administrator session.

After pairing, use the Fitness admin section to allow users and features, choose approved entities/areas/providers, and set defaults and user-selection permissions. Nothing is granted to users automatically. Users then open **Settings → Home Assistant**, separately from Profile settings. HA access stays local-network only.

## Capabilities

- Workout color-light feedback and any approved HA TTS entity/speaker.
- Approved training areas with independent room following for lights, TTS and music, and destination selection for the next Cast launch.
- Audio browsing/playback through approved HA Media Source roots and `play_media` players. Music Assistant players can be selected when they expose that HA capability; not every provider library has a Media Source adapter.
- Music room handoff restarts only playback started by Fitness and still identified as that item on the previous player. Other playback remains untouched; queues/position are not transferred.
- Explicit `ai_task.generate_data` entities; no generic conversation-agent home control.
- Read-only selected numeric sensors from installed supported fitness-provider integrations. This does not import workout history or add cloud accounts. Configure provider accounts in HA.
- Existing Cast launch/stop and optional read-only Fitness sensor mirrors.

## Manual setup and independent domain controls

Advanced manual setup remains available with a `ws://` or `wss://` Fitness bridge URL and matching `FITNESS_HA_BRIDGE_TOKEN`. Public destinations require WSS and a token of at least 24 characters. LAN IPs and `.local` hosts also permit WS.

The HA Configure options retain an independent service-domain allowlist. Existing manual entries may need `ai_task` added to enable AI. The connection handshake now advertises those domains. Fitness applies its own allowlist; neither `fitness` nor `fitness_bridge` can be delegated.

## Tests and acceptance

Run `python -m pytest -q tests` and `node tests/test_pairing_browser.cjs`.
The tests exercise production protocol definitions using HA service/registry doubles and the actual OAuth script using browser/network doubles. The matched Fitness repository includes HTTP/WebSocket and real Chromium acceptance tests.

A live HA Core installation and physical devices were not available in the build environment. Install both test builds and verify HA OAuth, one TTS utterance, one light cue, room changes, media playback, revocation and restart behavior on your installation before adopting this build.

Official references: [HA auth](https://developers.home-assistant.io/docs/auth_api/), [WebSocket API](https://developers.home-assistant.io/docs/api/websocket/), [AI Task](https://www.home-assistant.io/integrations/ai_task/).
