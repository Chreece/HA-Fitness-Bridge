# HA-Fitness Bridge — optional Home Assistant module

This directory is the separately installable Home Assistant module for **standalone Fitness Server**. Home Assistant is not part of Fitness: it may be installed, disabled, restarted, disconnected or removed without affecting Fitness accounts, workouts, device ingestion, dashboards, cloud sync, media, speech, Circle or storage.

The bridge owns only bounded HA-specific I/O:

- read-only mirroring of Fitness-owned sensor projections;
- bounded HA area/entity catalogs used by Fitness when HA is connected;
- allow-listed HA service calls for smart-home output;
- exact-target Cast launch/stop;
- workout-light output and optional HA speaker/TTS fallback.

Fitness Server remains the source of truth and independently re-checks service domains and entity/cast boundaries.

## Installable bridge artifact

Run from the repository root:

```bash
python tools/build_ha_bridge.py --output HA-Fitness-Bridge.zip
```

The deterministic archive contains:

```text
custom_components/fitness_bridge/
hacs.json
README.md
```

It can be unpacked into a Home Assistant configuration directory for the parallel/cutover validation stage. The bridge currently keeps the `fitness_bridge` domain deliberately separate from the legacy monolithic `fitness` domain so both can coexist during migration rehearsal. The legacy `custom_components/fitness` tree is not modified by this package.

## Configuration

Default local WebSocket endpoint:

```text
ws://127.0.0.1:8732/api/v1/bridge/home-assistant
```

The bridge token must match `FITNESS_HA_BRIDGE_TOKEN` when configured on Fitness Server. Plain `ws://` is accepted only for loopback/private/link-local or `.local` destinations. Public/non-local endpoints require `wss://` and a bridge token of at least 24 characters.

The Home Assistant service-domain list is configurable but may not delegate the `fitness` or `fitness_bridge` domains. Fitness Server applies its own fixed allow-list again, so the HA-side option cannot broaden server authority.

## Home Assistant lifecycle contract

The bridge follows the current config-entry style used by Home Assistant 2026.8/2026.9:

- `ConfigEntry.runtime_data` owns the live bridge client;
- `Platform.SENSOR` is used for platform forwarding;
- setup starts the reconnecting client and forwards the sensor platform;
- unload first unloads the platform, then stops the bridge client;
- options reload the entry through its update listener;
- mirrored sensors read only from `entry.runtime_data`;
- diagnostics are bounded and never include the bridge URL/token or Fitness credentials.

The bridge is translated into the same 15 languages currently supported by HA-Fitness: de, el, en, es, fr, it, ja, ko, nl, pl, pt, ru, tr, uk and zh.

## Validation status

The repository includes a Home Assistant lifecycle contract harness covering config-entry setup/reload/unload, runtime data, sensor creation, diagnostics and bridge packaging. The API shape was also checked against current Home Assistant developer/core sources.

A full Home Assistant runtime is not installed in the migration build environment, so the packaged source does not falsely claim an in-build HA Core boot. Phase 21 closes the production gate operationally instead: configure this bridge alongside legacy `fitness`, create the final frozen migration snapshot, retire the legacy integration with `fitness-server-deploy ha-bridge-finalize`, start the real Home Assistant installation, then run `fitness-server-deploy ha-bridge-verify`. That verification succeeds only when the running bridge has actually connected to Fitness Server. The exact pre-retirement HA state can be restored with `ha-bridge-rollback` while HA is stopped.
