# Import .vpn files and keys on the router

[Русский](ROUTER-IMPORT.md) | **English**

Since v0.3.0, a new Amnezia export can replace an existing client profile after server migration or reinstallation. The profile name retains the same OpkgTun, policies, routes, PingCheck and interface priority. The new server must still allow the required destinations in AllowedIPs. This does not migrate server settings.

Supported inputs: guest AmneziaWG `.vpn` exports and `.txt` files containing a `vpn://` key with a complete client configuration. Subscription/API or administrative keys without client credentials cannot be converted offline. See [format limitations](CONVERTER.en.md). Processing is local. Use a separate client identity for every device.

## One-time setup

In the router Entware SSH shell:

```sh
opkg update
opkg install python3-light python3-codecs
/opt/bin/python3 -c 'import argparse, base64, getpass, ipaddress, json, pathlib, zlib; print("Python modules OK")'
```

Requires Python 3.10+. Packages are available in the [official ARM64 Entware repository](https://bin.entware.net/aarch64-k3.10/). Python only runs during conversion; there is no persistent Python daemon. Additional memory usage has not been measured on the router.

For new installations, follow [INSTALL](../INSTALL.en.md). The installer deploys the converter. Instead of preparing `.conf` on a PC, upload an export to `/opt/tmp/new.vpn` and run:

```sh
/opt/etc/init.d/S99awg3 import /opt/tmp/new.vpn router
/opt/etc/init.d/S99awg3 up
```

Importing while stopped stores `router.conf` without starting the service. Configure routing and PingCheck separately.

### Update an existing v0.1/v0.2 installation

Download the v0.3.0 or newer installation archive from [Releases](https://github.com/Parsefall/amnezia-netcraze/releases/latest), upload to `/opt/tmp` and extract into a fresh directory:

```sh
mkdir -p /opt/tmp/awg3-v030
tar -xzf /opt/tmp/awg3-netcraze-arm64-userspace.tar.gz -C /opt/tmp/awg3-v030
sh /opt/tmp/awg3-v030/awg3-userspace/router/update-importer.sh
```

This updater verifies package checksums, backs up scripts, and replaces only the service, watchdog, parser and converter. It leaves daemon binaries, profiles and autostart flags intact and does not reapply profiles. Do not use the regular `install.sh` for a live update: it requires stopped engine processes.

The new update/import workflow has automated mocked-router coverage but **has not yet been tested on the physical NC-1012**. Use local SSH and retain access to provider-first routing in the web UI.

## Replace with one command

Read the current profile name with `/opt/etc/init.d/S99awg3 status`. For `OpkgTun0 <- router.conf`:

```sh
/opt/etc/init.d/S99awg3 import /opt/tmp/new.vpn router
# Or a text file containing the key:
/opt/etc/init.d/S99awg3 import /opt/tmp/new.txt router
```

The last argument is the **existing name without .conf**. For `pars.conf`, use `pars`, not `router`. Unknown targets are rejected while running. Previous files are saved under `/opt/etc/awg3/backups/imports/`.

## Automatic upload-and-rename workflow

Enable once:

```sh
/opt/etc/init.d/S100awg3-watchdog enable
```

While the service runs, the watchdog processes the inbox about every 30 seconds. Autostart also processes it. Stopping the VPN stops background processing; import never independently starts an intentionally stopped VPN.

PowerShell on the PC, for `router.conf`:

```powershell
scp -O -P 22 "C:\Users\you\Downloads\new.vpn" root@192.168.1.1:/opt/etc/awg3/inbox/router.vpn.part
ssh -p 22 root@192.168.1.1 'mv /opt/etc/awg3/inbox/router.vpn.part /opt/etc/awg3/inbox/router.vpn'
```

For text keys replace `.vpn` with `.txt` in both commands. For `pars.conf`, use `pars` as the destination basename. An SFTP client can upload `.part` then rename it. **Do not upload directly to the final filename**: it may be read before transfer completes. Do not submit both input formats for the same profile at once.

Processed inputs move into private `/opt/etc/awg3/inbox/item.*/` directories, with a `result` file. Rejected files are not repeatedly retried. Unknown profile names remain untouched in the inbox. Backups and exports contain secrets; never publish them and remove obsolete copies manually.

```sh
cat /opt/etc/awg3/inbox/item.*/result
/opt/etc/init.d/S99awg3 status
ndmc -c "show ping-check"
```

## Behavior and limits

- Converter and router parser validate before replacement. Router import explicitly removes IPv6; IPv4 is required.
- Keys, peer, Endpoint, Address and AWG settings are replaced. Exported DNS is omitted; firmware DNS remains in control. Missing MTU defaults to 1280.
- The existing OpkgTun, priority and routes are retained. Later startup also avoids resetting existing interfaces with `ip global auto`.
- Engine/NDMS rejection restores the old file and attempts live rollback. Rollback failure is reported. Power loss or SIGKILL is not a transactional rollback guarantee.
- Applied configuration is **not proof of server connectivity**. Verify a fresh handshake and traffic. Use [PingCheck](HEALTHCHECK.en.md) for availability; actual outage failover remains untested.
- Profiles persist on storage. Import does not save firmware configuration; startup reapplies the profile address. Save policy/PingCheck changes separately.
- A manually configured route to the old Endpoint is not updated. Confirm the new server is reached through the ISP, especially with VPN-first routing: `ip -4 route get NEW_IP`. Automatic endpoint-exception management is not implemented.

For manual rollback, copy the desired private backup to `/opt/tmp/old.conf`, then run `/opt/etc/init.d/S99awg3 import /opt/tmp/old.conf router`, using the correct profile name. Explicit import also accepts native `.conf`; the inbox only processes `.vpn` and `.txt`.

## v0.7.0 CLI

```sh
/opt/etc/init.d/S99awg3 create /opt/tmp/new.vpn second
/opt/etc/init.d/S99awg3 tunnel-down second
/opt/etc/init.d/S99awg3 import /opt/tmp/replacement.vpn second
/opt/etc/init.d/S99awg3 tunnel-up second
/opt/etc/init.d/S99awg3 delete second
```

`create` creates and starts a separate tunnel; `import` replaces a profile. Pause persists across reboot. `delete` preserves a private backup and removes the selected interface; save firmware configuration separately afterwards. See [multiple tunnels](WEB.en.md#multiple-tunnels-v070).
