# Changelog

[Русский](CHANGELOG.md) | **English**

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
