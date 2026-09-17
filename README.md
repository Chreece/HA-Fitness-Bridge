# HA-Fitness Bridge

**HA-Fitness Bridge** is the separately installable, open-source Home Assistant integration for **Fitness Server**.

Home Assistant is an optional module around Fitness, not part of Fitness itself. Fitness must continue to work if Home Assistant is disabled, restarted, disconnected, not installed, or the bridge is removed. This repository therefore owns the complete Home Assistant side of the connection and is versioned/released independently from Fitness Server.

## Architecture boundary

The bridge owns only bounded Home Assistant-specific I/O:

- read-only mirroring of Fitness-owned sensor projections into Home Assistant;
- bounded HA area/entity catalogs used by Fitness while the bridge is connected;
- allow-listed HA service calls for smart-home output;
- exact-target Cast launch/stop;
- workout-light output and optional HA speaker/TTS fallback.

Fitness Server remains the source of truth for Fitness accounts, profiles, workouts, devices, health data, plans, media, Circle and storage. The bridge must not become a hidden runtime dependency of Fitness.

The repositories communicate only through the versioned bridge protocol. The Home Assistant integration must not import Fitness Server internals, and Fitness Server must not import Home Assistant integration code. Either side may be upgraded, restarted or removed independently.

## Privacy and credentials

Fitness Server does **not** store Home Assistant access tokens or Home Assistant user credentials.

Pairing uses the dedicated bridge credential/protocol. The bridge exposes only the capabilities and service domains explicitly allowed by its configuration, while Fitness Server independently applies its own fixed allow-list and target validation again.

Diagnostics are bounded and must not expose bridge credentials, Fitness credentials or private URLs containing secrets.

## Open source

This repository is licensed under the **MIT License**. Contributions and independent review are welcome.

Keeping the bridge in its own repository also means its source, releases, issue tracker and HACS installation can remain open even if the licensing or release model of Fitness Server changes later.

## Installation

The Home Assistant custom integration lives at:

```text
custom_components/fitness_bridge/
```

For HACS, add this repository as a custom integration repository until it is accepted into the default HACS catalog.

A deterministic ZIP can also be built from the repository root:

```bash
python tools/build_ha_bridge.py --output HA-Fitness-Bridge.zip
```

The archive contains:

```text
custom_components/fitness_bridge/
hacs.json
README.md
LICENSE
```

The integration deliberately uses the `fitness_bridge` domain. It does not take ownership of the legacy monolithic `fitness` domain, allowing parallel migration/testing where needed.

## Configuration

Default local Fitness bridge endpoint:

```text
ws://127.0.0.1:8732/api/v1/bridge/home-assistant
```

Plain `ws://` is accepted only for loopback/private/link-local or `.local` destinations. Public/non-local endpoints require `wss://` and a sufficiently strong bridge credential.

The Home Assistant service-domain list is configurable but may not delegate the `fitness` or `fitness_bridge` domains. Fitness Server applies its own allow-list again, so the Home Assistant-side option cannot broaden server authority.

## Home Assistant lifecycle contract

The integration follows current config-entry patterns:

- `ConfigEntry.runtime_data` owns the live bridge client;
- `Platform.SENSOR` is used for platform forwarding;
- setup starts the reconnecting client and forwards the sensor platform;
- unload first unloads the platform, then stops the bridge client;
- options reload the entry through its update listener;
- mirrored sensors read only from `entry.runtime_data`;
- diagnostics remain bounded and redact secrets.

Translations are included for the languages currently supported by the bridge.

## Compatibility

Bridge protocol compatibility is independent from repository version numbers. Breaking protocol changes must increment the protocol version and document the minimum compatible Fitness Server and HA-Fitness Bridge releases.

A newer bridge should fail closed when connected to an unsupported server protocol rather than silently widening permissions or guessing behavior.

## Development and releases

The bridge should be tested and released independently from Fitness Server. Public issues for Home Assistant-specific bugs belong in this repository; Fitness Server issues belong in the Fitness repository.

Before a public release:

1. validate the Home Assistant config-entry lifecycle and diagnostics;
2. verify reconnect, unload/reload and server restart behavior;
3. verify that allowed services and entity targets remain bounded;
4. verify pairing against a real Fitness Server installation;
5. build and inspect the deterministic ZIP;
6. publish a tagged GitHub release for HACS users.

See `CONTRIBUTING.md` and `SECURITY.md` for contribution and security-reporting guidance.
