# Userspace integration architecture

[Русский](ARCHITECTURE.md) | **English**

`S99awg3` → `amneziawg-go -f opkgtunN` → kernel TUN.
`awg setconf` sends configuration over `/var/run/amneziawg/opkgtunN.sock`. No amneziawg.ko module is loaded. The NDMS `OpkgTunN` object integrates the interface with firmware settings.

## State

- `/opt/etc/awg3/managed.tsv`: profile path, index, and NDMS name, separated by tabs.
- `/opt/etc/awg3/enabled`: permission to start when Entware boots.
- `/opt/etc/awg3/watchdog-enabled`: separate watchdog opt-in flag.
- `/var/run/awg3/running`: service startup marker for the current boot.
- `/var/run/awg3/opkgtunN.pid`: PID verified against /proc/PID/exe and cmdline.
- `/var/run/awg3/service.lock`: serializes start/stop/repair/save/install.
- `/opt/etc/awg3/conf/parsed`: generated files with restricted permissions.

Deleting a profile does not automatically free its index. The state entry and object remain so an index with existing policies cannot be reused accidentally. Removing a binding requires a separate manual operation after checking routes.

Unknown existing interfaces are not removed or taken over. NDMS may restore a persistent TUN at boot. Attaching to it requires a managed.tsv record, a tun_flags entry in sysfs, and the OpkgTun NDMS type. The kernel refuses to open an already occupied TUN queue.

## Startup and shutdown

up validates all profiles and required dependencies first. Index ownership is saved atomically before configuration so a later failure does not lose the record. It then creates the NDMS object, starts the engine, applies AWG parameters and IP/MTU/DNS, and brings the interface up. Firmware configuration is not automatically saved to flash; use save.

stop clears the running marker, stops the watchdog, and takes owned interfaces down. TUN processes stay alive to preserve interfaces and bindings. This is not a complete routing rollback: traffic may fall back to WAN if the policy explicitly allows it.

Replacing an engine binary while its process is running is prohibited. Disable autostart and reboot before an update; the installer then backs up replaced files. A failed step does not automatically restore all network configuration; an error is returned to the caller.

## Watchdog

Checks UAPI availability and invokes repair on failure, no more frequently than every 180 seconds. A healthy interface is not restarted just because its last handshake is old. This does not check VPN-server or Internet availability. The watchdog requires explicit enable and the running marker.

## Profiles

The parser checks syntax, allowed fields, IPv4/CIDR, MTU, and interface names. It uses temporary files and umask 077. Only validated IP/numeric values enter shell commands; AWG keys are data, never executed.

awg itself validates cryptographic and protocol values. If it rejects the profile, startup returns an error; earlier changes may already have been applied.

The wrapper does not support IPv6 or multiple peers. prepare_profile.py creates a separate IPv4 copy with the explicit --ipv4-only option and never overwrites the source.

## Routing and health

The parser does not create a default route even for AllowedIPs=0.0.0.0/0. Existing routes are not removed. Full-tunnel or selected-IP routing is configured separately in NDMS. Ping Check is assigned and saved using [HEALTHCHECK.en.md](docs/HEALTHCHECK.en.md); the UAPI watchdog does not replace Internet checks.
