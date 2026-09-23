# Amnezia Netcraze

[Русский](README.md) | **English**

Manage AmneziaWG in a browser: upload a `.vpn`/`.txt` export or paste a full client key, create multiple tunnels and configure their names and PingCheck. The panel runs on the router. **No desktop converter or pre-generated `.conf` is required.** [Installation](INSTALL.en.md) · [Panel guide](docs/WEB.en.md).

AmneziaWG 3.1 for Netcraze through Entware: a ready-to-install ARM64 package, a userspace engine, and integration with the router's routing policies. No `amneziawg.ko` kernel module is required.

**Tested ONLY on the project owner's Netcraze Giga NC-1012:** hardware revision **1210C000**, ARM64 (`aarch64`), firmware **5.1.5 / 5.01.C.5.0-0**, Linux **4.9-ndm-5**, Entware on external storage, and `/dev/net/tun`. Compatibility with other models or firmware versions is not claimed.

## Download and install

1. Download `awg3-netcraze-arm64-userspace.tar.gz` and its `.sha256` file from [Releases](https://github.com/Parsefall/amnezia-netcraze/releases/latest).
2. Create a **separate Amnezia client for the router**. Do not use the same client profile on the PC and router simultaneously.
3. Follow the [installation guide](INSTALL.en.md): install the engine and panel, then upload `.vpn`/`.txt` or paste your key in **Tunnels → Add tunnel**.
4. Choose a [routing setup](docs/ROUTING.en.md).
5. Configure [Ping Check](docs/HEALTHCHECK.en.md), verify connectivity, and enable autostart.

The installer checks file hashes, backs up replaced files, and **does not start the VPN, import keys, or change connection priorities**. Starting the VPN does not add a default route either: routing is an explicit user decision.

## System requirements

- A router with 64-bit ARM (`aarch64`), Entware at `/opt` and root access to its SSH shell.
- TUN device `/dev/net/tun`, `ndmc` and firmware support for `OpkgTun` interfaces; the Ping Check component for connectivity monitoring.
- Compatible system libraries for `awg`: `/lib/ld-musl-aarch64.so.1`, libc and libgcc. This package does not support MIPS/MIPSEL or 32-bit ARM.
- Python **3.10 or newer**, Python packages required by the HTTPS panel, `openssl-util` and `ca-bundle`. Dependency installation commands are in the [installation guide](INSTALL.en.md).
- Storage for the application, dependencies and backups. Panel updates require at least **48 MiB free before downloading**; backup space is checked separately.
- Available RAM for the VPN engine and panel. The tested router has **512 MiB RAM**; this is its hardware specification, not an established minimum. Memory usage grows with the number of tunnels.
- A JavaScript-enabled browser with access to the router's LAN.

## Limitations

- One peer and one IPv4 address per profile. The wrapper does not configure IPv6 through the VPN.
- AllowedIPs controls addresses allowed inside AWG; it does not create NDMS routes.
- Routing operates on devices and IP addresses, not individual Windows applications.
- The watchdog checks the local process; Ping Check checks traffic delivery. They serve different purposes.

## Documentation

- [Installation, updates, and removal](INSTALL.en.md)
- [Routes and policies](docs/ROUTING.en.md)
- [Availability monitoring and failover](docs/HEALTHCHECK.en.md)
- [Troubleshooting](docs/TROUBLESHOOTING.en.md)
- [Architecture](ARCHITECTURE.en.md), [building](docs/BUILD.en.md)
- [Changelog](CHANGELOG.en.md), [provenance and licenses](NOTICE.en.md)

The engine is official [amneziawg-go](https://github.com/amnezia-vpn/amneziawg-go) with a local S4 race fix. This is an independent project, not an official Netcraze or Amnezia product.
