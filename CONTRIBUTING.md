# Contributing to HA-Fitness Bridge

Thanks for helping improve the Home Assistant bridge for Fitness Server.

## Scope

This repository owns the **Home Assistant side** of the Fitness ↔ Home Assistant connection. Changes should preserve the separation between the two projects:

- do not import Fitness Server internals into the Home Assistant integration;
- do not move Fitness-owned state, accounts, workouts, device ingestion or business logic into Home Assistant;
- keep the bridge optional so Fitness continues to work without Home Assistant;
- keep Home Assistant service execution explicitly allow-listed and target-bounded;
- do not add storage of Home Assistant access tokens or user credentials to Fitness Server.

## Compatibility

The bridge protocol is the compatibility boundary. Additive changes should remain backward-compatible where practical. Breaking protocol changes must increment the protocol version and document minimum compatible releases on both sides.

Unsupported protocol combinations should fail closed rather than guessing behavior.

## Pull requests

Please keep pull requests focused. For behavioral changes, include or update validation coverage where possible and describe:

- the Home Assistant lifecycle affected;
- the protocol/capability affected;
- whether the change is backward-compatible;
- the security/permission boundary involved;
- how reconnect, reload and unload behavior was tested.

Never commit production credentials, bridge pairing secrets, Home Assistant tokens, private URLs containing secrets, or exported user data.

## Local checks

At minimum, verify Python syntax for the integration and build the deterministic package:

```bash
python -m compileall custom_components/fitness_bridge
python tools/build_ha_bridge.py --output /tmp/HA-Fitness-Bridge.zip
```

Before a release, also test against a real Home Assistant installation and a compatible Fitness Server.
