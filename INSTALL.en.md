# Installing Amnezia Netcraze

[Русский](INSTALL.md) | **English**

An optional [web panel runs on the router](docs/WEB.en.md): import files/keys, control VPN, view status and restore backups in a browser.

You can import `.vpn` or a key in `.txt` **directly on the router**, then rotate profiles by uploading to its inbox. See [router import and update](docs/ROUTER-IMPORT.en.md).

## Prerequisites

You need Entware, root access to its shell, storage mounted at `/opt`, and `/dev/net/tun`. See [README](README.en.md) for the tested model and firmware. This guide does not cover installing Entware itself.

Back up your router configuration using its web interface. Keep the ISP first in the default connection policy. Use the router's local address for recovery.

Create a **separate client for the router** on your VPN server and export its AmneziaWG `.conf`. Do not reuse an active Windows profile: with identical keys, the server can switch packet delivery between devices. Never publish personal profiles.

Examples use `192.168.1.1` and SSH port **22**, as tested. Replace `22` if your Entware SSH server uses another port. SCP uses uppercase `-P`; SSH uses lowercase `-p`. The session must open a shell with a prompt such as `~ #`, not only the firmware CLI.

## 0. If you only have an Amnezia key

For direct router import, complete installation steps 1–2 below, then [install Python and import the export](docs/ROUTER-IMPORT.en.md) instead of copying a native `.conf` in step 3. This also supports automatic future replacement. PC conversion below remains an alternative.

If you have a **`.vpn` file or `vpn://…` key**, use the [offline converter](docs/CONVERTER.en.md): download the converter ZIP from the release, extract it, run `python tools/convert_profile.py --gui --lang en` (Python 3.10+ with tkinter required), select the file or paste the key, and save router.conf. Then proceed to step 1.

The converter extracts an embedded AWG client profile; subscription or full-access keys may not contain one. In that case, use the export methods below. Renaming .vpn to .conf does not convert it. A QR code or standalone PrivateKey is not sufficient.

### Your own Amnezia server

1. Open AmneziaVPN using a connection with full access to your server.
2. Open Share VPN, create a separate user for the router, and choose the **AmneziaWG** protocol.
3. Select **AmneziaWG native format**, not the format for the AmneziaVPN app. Labels may vary between application versions.
4. Save the `.conf` file, for example `amnezia_for_awg.conf`, and rename a copy to `router.conf` for the commands below.

If someone only gave you a guest `vpn://` key, ask them for a **separate native-format AmneziaWG profile for the router**. Possessing a key does not necessarily grant export or server administration permissions.

[Official export instructions](https://docs.amnezia.org/documentation/instructions/amnezia-hosting-sharing/).

### Amnezia Premium

Open the Personal Dashboard using the official email/app link, sign in with your subscription key, find Configuration Files, and download a `.conf` for the desired location. Generating a configuration uses a connection slot. Do not paste a subscription key into router.conf.

Amnezia documents these configurations as AWG 3.1, but **Amnezia Premium has not been separately tested with this project**. Automatic subscription updates are not implemented: a revoked or changed configuration requires a new file.

[Official Personal Dashboard instructions](https://docs.amnezia.org/documentation/instructions/personal_dashboard/).

### Recognizing a suitable file

Inspect the file locally without sharing its contents. Expect `[Interface]` and `[Peer]` sections, Address, PrivateKey, PublicKey, AllowedIPs, Endpoint, and the server-issued AmneziaWG parameters. All connection settings are required, not just a key. These field names alone do not replace parser and server validation.

The installer does not accept VLESS/XRay/OpenVPN or other configuration formats. Step 3 covers IPv4 limitations and preparing a copy. Once you have a suitable router.conf, proceed to step 1.

## 1. Download and verify — Windows PowerShell

Download the archive and `.sha256` from the [release](https://github.com/Parsefall/amnezia-netcraze/releases/latest) into the same folder. Open PowerShell **in that folder** (`PS C:\...>`):

```powershell
$expected = ((Get-Content .\awg3-netcraze-arm64-userspace.tar.gz.sha256 -Raw).Trim() -split '\s+')[0]
$actual = (Get-FileHash .\awg3-netcraze-arm64-userspace.tar.gz -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw 'Checksum mismatch. Do not install this archive.' }
scp -O -P 22 .\awg3-netcraze-arm64-userspace.tar.gz root@192.168.1.1:/opt/tmp/
ssh -p 22 root@192.168.1.1
```

`-O` selects the legacy SCP protocol because Entware may not provide SFTP. Password characters are not displayed while typing.

## 2. Install — router SSH shell

Run the commands in order. Stop if any command fails.

```sh
mkdir -p /opt/tmp/awg3-install
tar -xzf /opt/tmp/awg3-netcraze-arm64-userspace.tar.gz -C /opt/tmp/awg3-install
cd /opt/tmp/awg3-install/awg3-userspace
sh router/install.sh
```

The installer checks the files and both ARM64 executables. Replaced files are backed up under `/opt/etc/awg3/backups/<date-PID>`. This is a project file backup, not a complete NDMS configuration backup. Autostart is disabled after installation. Existing profiles are preserved.

`amneziawg-go --version` may report `0.0.20250522`: this is a constant in the upstream source. The actual tag, commit, and SHA256 are recorded in `prebuilt/kn-1012/BUILD-INFO.json`.

## 3. Copy your profile — Windows PowerShell

Open another PowerShell tab **without SSH**. The example assumes `router.conf` is in the current directory:

```powershell
scp -O -P 22 .\router.conf root@192.168.1.1:/opt/etc/awg3/conf/router.conf
```

Use ASCII letters, digits, `_`, `-`, and `.` in the filename and end it with `.conf`. Every `.conf` in the directory is active; do not copy the example profile there.

The wrapper supports one IPv4 Address, IPv4 DNS, and one peer. If AllowedIPs includes `::/0`, use Python and the project source to create a separate copy:

```powershell
python build/prepare_profile.py original.conf router.conf --ipv4-only
```

The utility removes IPv6 only from AllowedIPs. IPv6 Address/DNS entries still require a valid IPv4-only profile. Do not invent keys, Endpoint settings, or obfuscation parameters, or replace them with sample values.

## 4. Start — router SSH shell

```sh
chmod 600 /opt/etc/awg3/conf/router.conf
/opt/etc/init.d/S99awg3 up
/opt/etc/init.d/S99awg3 status
```

Note the assigned `OpkgTunN` / `opkgtunN`: the index is not necessarily 0. The web interface uses the profile filename as the connection name, `router` here. Wait for a handshake. A connected status alone does not prove Internet access.

## 5. Configure routing and test the PC

Choose **one** setup in [ROUTING.en.md](docs/ROUTING.en.md):

- Selected IPs through VPN: ISP first, static routes to the VPN, no default route through VPN.
- An entire device through VPN: a separate policy and an explicitly added tunnel default route; start with one test device.

Disable the PC's VPN application while testing. Check HTTPS and the external IPv4 address on the intended path. Windows commands belong in PowerShell, not the router SSH shell. Then configure [Ping Check](docs/HEALTHCHECK.en.md).

## 6. Save and enable autostart — router SSH shell

Only after successful testing:

```sh
/opt/etc/init.d/S99awg3 save
/opt/etc/init.d/S99awg3 enable
```

`Saving (cli)` identifies the source of the save command. The current NDMS configuration is saved. The autostart flag is stored separately on `/opt`.

Reboot when convenient and repeat status, DNS, HTTPS, and external IP checks. If connectivity fails, use the local web interface to put the ISP first and return the test PC to the default policy. Reconnect SSH after rebooting.

## Updating

Return clients to the ISP. Preserve keys, routes, and managed.tsv.

```sh
/opt/etc/init.d/S99awg3 disable
```

Reboot: stop keeps TUN processes alive, and the installer refuses to replace a running engine. After booting, repeat installation, manual startup, validation, and enable/save. The installer does not remove old routes: check for an existing default route pointing to the VPN. Version 0.1.0 and later no longer create it automatically.

Ping Check is saved in NDMS independently of the package. The optional UAPI watchdog is enabled separately, does not replace Ping Check, and is not needed for the initial setup.

## Removal and rollback

Return clients to the ISP policy, disable your VPN routes, and run `/opt/etc/init.d/S99awg3 disable`. You can run `sh router/uninstall.sh` from the extracted archive; it preserves profiles, binaries, backups, and NDMS objects. This is not a complete network rollback. Disable autostart and reboot before restoring files from backup. Do not restore the incompatible `amneziawg.ko` kernel module.
