# Security policy

HA-Fitness Bridge sits on a trust boundary between Fitness Server and Home Assistant. Security reports are welcome and should be handled privately until a fix is available.

## Reporting a vulnerability

Please do **not** open a public issue for a vulnerability that could expose credentials, private Fitness data, Home Assistant state, or unauthorized service execution.

Use GitHub's private vulnerability reporting for this repository when available. If that option is not available, contact the repository maintainer privately through GitHub and include only the minimum information needed to establish contact; sensitive reproduction details can then be exchanged privately.

## Security invariants

Changes must preserve these rules:

- Fitness Server does not store Home Assistant user credentials or long-lived Home Assistant access tokens.
- The bridge protocol is authenticated and unsupported protocol versions fail closed.
- Home Assistant service calls are explicitly allow-listed on the bridge side and independently bounded again by Fitness Server.
- The `fitness` and `fitness_bridge` domains cannot be delegated back through generic service execution.
- Entity IDs, Cast targets and URLs are validated before execution.
- Diagnostics and logs must not expose bridge credentials, Fitness credentials, authorization material or private URLs containing secrets.
- Disabling or unpairing the bridge must revoke the active connection promptly.
- Fitness must continue functioning when the bridge is unavailable or removed.

## Supported versions

Until the first stable release, security fixes are applied to the latest development version only. After stable releases begin, this file should be updated with an explicit supported-version table.
