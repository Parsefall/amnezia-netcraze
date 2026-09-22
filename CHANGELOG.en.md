# Changelog

[Русский](CHANGELOG.md) | **English**

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
