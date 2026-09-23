# Validation and support boundaries

[Русский](VALIDATION.md) | **English**

Router observations were made on September 22, 2026.

## The only tested router

Netcraze Giga **NC-1012**, hardware **1210C000**, ARM64/aarch64, 512 MB RAM, firmware **5.1.5 / 5.01.C.5.0-0**, Linux **4.9-ndm-5**, Entware, /dev/net/tun. The project owner supplied the device results. Other models, revisions, and firmware versions have not been tested.

| Check | Result |
|---|---|
| Old kernel module | Failed to load: Unknown symbol crypto_chacha_init; excluded from release |
| ARM64 userspace engine and awg | Started on the device |
| AWG 3.1 handshakes and traffic | Confirmed |
| Router → VPN → 1.1.1.1 | 4/4 replies, about 85–91 ms |
| PC in a separate VPN policy | Ping to 8.8.8.8, DNS, HTTPS, and VPN connectivity confirmed by owner |
| Engine after reboot | Autostart, handshake, and subsequent traffic confirmed |
| VPN first in system policy | Connectivity loss observed; exact cause not established |
| OpkgTun0 Ping Check | Binding, successful probes, and saving confirmed |
| Actual outage / fallback / recovery | NOT tested: owner deferred the test |
| Selected IP routes | List validated and imported by owner; complete service coverage not verified |
| Memory | One observation: RSS ~46 MiB, peak ~226 MiB; not a load test |
| Final 0.1.0 scripts | Local tests; not reinstalled on the test device |

## Local checks

Shell parser: IPv4 prefixes /0–/32, CRLF, profile fields, rejection of shell injection, preservation of previous results on failure, DNS arguments, textual NDMS errors with exit code 0, and no automatic default route even with AllowedIPs=0.0.0.0/0.

Service: awg/NDMS errors, stable indexes, preservation of foreign interfaces, and refusal of repair after stop. Mocks do not replace NDMS testing.

Package: file allowlist, ELF64 AArch64, no dynamic interpreter in AWG-Go, binary hashes matching BUILD-INFO, per-file SHA256, and tar.gz contents.

## S4 fix

Official amneziawg-go v3.1.20260828, commit b5928efb6ca19f0153958460c3d141f04abc5c2e, built with Go 1.25.14, CGO_ENABLED=0, linux/arm64. The only local patch is build/patches/002-go-tun-padding-refresh.patch.

RoutineReadFromTUN read S4 before a blocking Read. Changing S4 while waiting could make the first payload use an outdated offset. The patch reloads the offset after Read, checks capacity, and moves the payload using an overlap-safe copy. Cryptographic algorithms are unchanged.

Before the patch, TestAWGDevicePing and an additional test reproduced the failure. After it, device/conn/replay/tai64n passed, along with 10 repetitions of TestRouterAWG31Profile (in-memory/UDP), TestRouterS4ChangeWhileReadBlocked, and TestAWGDevicePing: 70 test/subtest results, zero failures. Regression source is in tests/go_profile_smoke_test.go. These were Windows host tests, not router performance measurements.

Not verified: IPv6, every combination of AWG parameters, long-term stability, throughput limits, Docker build path, or failover during an actual outage. The awg CLI binary was inherited from the original project; its version and execution were confirmed, but bit-for-bit build reproducibility was not established.

## Converter 0.2.0

14 automated tests with synthetic keys cover qCompress/Base64URL and JSON exports, AWG parameter preservation, explicit IPv6 handling, damaged and oversized input, multiple profiles, absent client configuration, private no-overwrite output, and CLI behavior. Converted output was also checked with the project's actual shell parser. The converter has not processed the user's real .vpn export yet; manual GUI testing has not been performed. VPN-engine and failover validation status is unchanged.


## Router import v0.3.0

16 Python tests; service tests cover stable interface/priority, DNS/MTU normalization, malformed-input rejection, rollback after engine rejection, inbox .part handling and one-time consumption, and stopped-service import. Engine and NDMS are mocked. The new import workflow and live script updater have not yet been tested on physical hardware.


## Web panel v0.4.0

14 HTTPS/API tests and mocked-router browser validation passed. Details and limits: [WEB.en.md](docs/WEB.en.md#validation-and-resource-use). Panel not yet installed on router; RSS/CPU unmeasured.

## v0.5.0

Panel v0.5.0: 42 Python tests (16 converter, 14 HTTPS/API, 12 PingCheck). Edge against simulated firmware: apply, disable, save, interface selection, edited values retained on refresh, RU/EN and 390 px mobile layout. The owner confirmed v0.4.1 startup on NC-1012. The new form and actual VPN outage have not been tested on hardware.

## v0.6.0

45 Python tests; service regressions cover rename, persistence on startup, NDMS rejection retaining the old name and autostart disable without stopping. Edge checks cover status, button states, independent autostart, rename, RU/EN and mobile width. Firmware is simulated; new features have not been tested on physical hardware.

## v0.7.0

48 Python tests; service regressions cover a third tunnel, unchanged neighbours, duplicate-key rejection, pause during import/startup, retryable deletion failures, reserved deleted indexes and independent startup after global stop. Edge: minimal overview, scoped replacement, second-tunnel creation, PingCheck, pause/start/delete, RU/EN and mobile layout. Firmware is simulated; real concurrent tunnels on NC-1012 have not been verified.

## v0.8.0

69 Python tests, including 18 updater tests and 3 new HTTPS/API checks. Covers unsafe tar paths/links/duplicates, checksums, versions, changed-engine rejection, disk space, locks, key preservation, successful install, partial-write rollback, rollback failure and interruption. Browser: versions, checking, confirm/cancel, pinned version request, RU/EN and mobile layout. Installation tests use a temporary filesystem and mocked services; hardware updating remains untested.
