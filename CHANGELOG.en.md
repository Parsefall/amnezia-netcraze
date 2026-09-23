# Changelog

[Русский](CHANGELOG.md) | **English**

## 0.7.0

Minimal overview, Tunnels tab with per-tunnel settings, separate log. Multiple concurrent VPNs with independent start/pause/delete and scoped key/PingCheck controls. Startup and repair respect pause; duplicate client keys are rejected. Deletion saves a backup and reserves the old index. Physical hardware validation remains pending.

## 0.6.0

PingCheck-based connection status, state-aware buttons, independent autostart disable and persistent tunnel display names. Removed two overview captions. Uninstall now explicitly stops VPN. Firmware interface type is unchanged.

## 0.5.0

Panel PingCheck controls: IPv4 target, intervals and thresholds, enable/disable, explicit full-router configuration save. Isolated profiles, import locking, assignment rollback on failure, RU/EN. 12 simulated-firmware tests; actual outage failover remains untested.

## 0.4.1

Fixed panel startup on Entware without nohup. A shell trap ignores SIGHUP before exec Python; credentials, TLS certificate and VPN are unchanged. Added Linux startup/idempotency/SIGHUP/stop regression coverage.

## 0.4.0

An optional [web panel runs on the router](docs/WEB.en.md): import files/keys, control VPN, view status and restore backups in a browser.

Separate HTTPS service, password login, configured LAN subnet, RU/EN. 14 HTTPS/API tests and mocked-router browser checks passed. Physical NC-1012 installation and resource measurements remain pending.

## 0.3.0

You can import `.vpn` or a key in `.txt` **directly on the router**, then rotate profiles by uploading to its inbox. See [router import and update](docs/ROUTER-IMPORT.en.md).

Existing interface priority is preserved at startup. Import validates, backs up, and attempts rollback on apply errors. Added a script-only updater. Mocked-router tests passed; physical router validation pending.

## 0.2.0 — Amnezia profile converter

- Offline .vpn/vpn:// to router.conf conversion, with RU/EN GUI and CLI.
- Extracts embedded AWG profiles from Qt qCompress/Base64URL exports without contacting servers.
- Explicit IPv6 removal, validation, bounded decompression, and no output overwrites.
- Subscription/API and administrative exports without client profiles produce an actionable error.
- Standalone converter ZIP and updated RU/EN instructions. VPN engine and router service are unchanged.

## 0.1.1 — bilingual documentation

- Complete Russian and English documentation with language links.
- English guides included in the installation archive.
- Runtime scripts and VPN binaries are unchanged from 0.1.0; no router update is needed just for the translation.

## 0.1.0 — first public userspace release

- ARM64 amneziawg-go replaces the incompatible kernel module.
- S4 race during TUN reads fixed and covered by regression tests.
- Reworked installer, parser, service, and optional watchdog.
- Startup does not create a default route, so selected-IP routing does not turn into a full tunnel after a restart.
- NDMS error[code] messages are detected even with exit code 0.
- HeaderProtectionKey is hidden in status.
- Instructions cover SSH port 22, separate PC/router profiles, Ping Check, and policies.
- Actual VPN-outage failover is explicitly marked as untested.
