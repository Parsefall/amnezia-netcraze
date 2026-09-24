# Router web panel

[Русский](WEB.md) | **English**

## HTTP and HTTPS access

Both addresses work simultaneously with the same password and tunnel settings:

- **HTTP:** `http://192.168.1.1:8089`
- **HTTPS:** `https://192.168.1.1:8088`

Use your router LAN IP if it differs. Sign in separately at each address. HTTP sends passwords and uploaded profiles without encryption; use it only on a trusted LAN. Both listeners enforce the configured LAN subnet and authenticated actions.

Updating an existing panel enables HTTP on 8089 automatically; if HTTPS already uses 8089, HTTP defaults to 8090. Password and certificate are retained. For fresh setup, `--port` selects HTTPS and `--http-port` selects HTTP; use `--http-port 0` to disable HTTP. Existing installations may set the integer `http_port` in `/opt/etc/awg3/web/settings.json` and restart `S101awg3-web`. Ports must differ and be in 1024–65535. If either port is occupied, startup fails; panel updates attempt rollback. The updater continues to verify startup through HTTPS.

The v0.9.0 panel runs **on the router itself** through Entware. A computer or phone only provides the browser. It has its own HTTP and HTTPS addresses; it is not a card in Netcraze's built-in Applications page. Includes Russian and English UI.

Features: file/key import, existing-profile replacement, start/stop of the whole VPN service, autostart, watchdog/inbox, handshake timestamps, traffic counters, PingCheck controls and status, filtered log, backup restore and panel password change. Routing and device policies stay in the firmware UI.

## Install over an existing project installation

Requires Entware and Amnezia Netcraze. For a new router, first follow [VPN installation](../INSTALL.en.md); you can then import a profile through the panel. Prior hardware testing is limited to Netcraze Giga NC-1012, hw 1210C000, aarch64, NetcrazeOS 5.1.5, kernel 4.9-ndm-5. The owner confirmed v0.4.1 panel startup on this router; the new PingCheck form has only been tested with simulated firmware.

1. Download `awg3-netcraze-arm64-userspace.tar.gz` from [v0.9.0](https://github.com/Parsefall/amnezia-netcraze/releases/tag/v0.9.0). In PC PowerShell from the download directory:

```powershell
scp -O -P 22 .\awg3-netcraze-arm64-userspace.tar.gz root@192.168.1.1:/opt/tmp/
ssh -p 22 root@192.168.1.1
```

2. In the **router's Entware SSH shell**:

```sh
opkg update
opkg install python3-light python3-codecs python3-openssl python3-email python3-urllib python3-logging openssl-util ca-bundle
mkdir -p /opt/tmp/awg3-panel-update
tar -xzf /opt/tmp/awg3-netcraze-arm64-userspace.tar.gz -C /opt/tmp/awg3-panel-update
sh /opt/tmp/awg3-panel-update/awg3-userspace/router/install-web.sh
```

Python modules are split into packages in [ARM64 Entware](https://bin.entware.net/aarch64-k3.10/). No pip or third-party Python library is required. The installer checks imports/checksums, updates import scripts with backups, and installs the panel. Engine binaries/profiles are retained; VPN and routes are not restarted or changed.

3. Create your **panel password** (12–128 characters) and LAN binding:

```sh
/opt/bin/python3 /opt/lib/awg3/web/server.py --setup --bind 192.168.1.1 --network 192.168.1.0/24 --port 8088
/opt/etc/init.d/S101awg3-web enable
```

The hidden password prompt is separate from root/firmware credentials. Adjust both address and subnet to your actual LAN. Wildcard/public binding is prohibited. If 8088 is occupied, choose another free port above 1023.

4. Open **http://192.168.1.1:8089** or **https://192.168.1.1:8088** from the configured subnet. Exact IP/port matching is enforced; domain/CrazeDNS access is unsupported.

Setup creates a local self-signed certificate, so the browser will show a trust warning. Compare its SHA256 fingerprint against setup output before trusting it. Display the fingerprint again with:

```sh
/opt/bin/openssl x509 -in /opt/etc/awg3/web/cert.pem -noout -fingerprint -sha256
```

Keep this a home-LAN service: do not expose it using port forwarding or a public reverse proxy. Subnet checks do not replace guest-network isolation. Certificate lifetime is 825 days; rerun setup and restart the panel to renew it.

## Everyday use

- Open Tunnels → ⚙ for the intended tunnel, select a file or paste a key and choose Validate and apply. Add tunnel creates a new one while existing tunnels continue running.
- Import keeps the same OpkgTun, routes, policies and priority. See [router import](ROUTER-IMPORT.en.md) for format/rollback limitations. Export DNS is omitted, IPv6 removed, absent MTU defaults to 1280.
- Verify a fresh handshake, PingCheck and traffic after server migration. An available engine does not prove VPN connectivity. Update any manual exception route for the old Endpoint separately.
- Global controls under Settings affect the whole service; tunnel-card buttons affect only that tunnel. Disable under autostart only removes autostart.
- Restore applies a backup to its original profile. Private profiles/backups cannot be downloaded through the panel.
- Log viewing filters key-related lines and long secret-like strings. It is diagnostic output, not a complete log export; review before sharing.
- Panel autostart is separate; stopping VPN keeps the panel available. Sessions last one hour; changing the password invalidates all sessions.

## Service and recovery

```sh
/opt/etc/init.d/S101awg3-web status
/opt/etc/init.d/S101awg3-web restart
# Stop only the panel and disable its autostart:
/opt/etc/init.d/S101awg3-web disable
# Enable it again:
/opt/etc/init.d/S101awg3-web enable
```

Forgotten password or LAN changes: stop the panel, rerun `--setup` with the intended address/subnet, then enable it. This also replaces the certificate. Installer updates retain password and LAN configuration. Settings/private TLS key live under `/opt/etc/awg3/web/`; startup log: `/opt/var/log/awg3-web.log`. Do not publish the settings directory. The general uninstaller also stops the panel while retaining data.

## Validation and resource use

14 real HTTPS/API tests cover authentication, cookies, Host/Origin/CSRF, LAN checks, login/request limits, session revocation, fixed commands, upload cleanup, restore, redaction and password changes. NDMS/engine are mocked. An Edge browser test covered login, overview, import, restore, RU/EN, 390 px mobile width and logout without JavaScript errors. Browser preview used local test HTTP; real TLS was tested separately by the API suite.

The panel keeps one Python process running, with up to 8 request handlers. **Router RSS/CPU measurements are pending.** Check after installation:

```sh
p=$(cat /var/run/awg3/web.pid)
grep -E '^(Name|VmRSS|VmHWM|Threads):' /proc/$p/status
```

The browser polls every 15 seconds only while visible. No CDN, analytics or remote assets. Backend runs as root to control VPN but only exposes fixed actions without shell/arbitrary command execution. Passwords use salted PBKDF2-SHA256 with 600000 iterations; HttpOnly/Secure/SameSite cookies, CSRF tokens, Host/Origin checks and TLS 1.2+ are used. This is not a claim of an independent security audit.


## Fixing nohup: not found in 0.4.0

Dependencies, password and certificate setup do not need repeating. Replace only `/opt/etc/init.d/S101awg3-web` with the 0.4.1 file, chmod 755 and enable it using the full path. Startup now uses shell builtins; nohup is not required. Router logs confirmed this issue on NC-1012; corrected hardware startup is awaiting confirmation.

## PingCheck in the panel (v0.7.0)

Open **Tunnels → ⚙ → PingCheck** for the intended tunnel and choose **Enable / apply**. Recommended values: `1.1.1.1`, 10-second interval, 3-second timeout, 3 failures, 2 successes. The fields are a new-settings template; the selected tunnel’s current state appears above them. Automatic refresh preserves edited fields.

Checks run in firmware using ICMP, without restarting the interface. The panel creates a separate profile for the selected VPN rather than editing a shared ISP profile. Disable detaches the check only from the selected VPN. Errors trigger an attempt to restore the previous assignment; unconfirmed rollback is explicitly reported. Routes and priorities are unchanged.

After applying, wait for `status: pass`. Choose **Save router configuration** to retain changes after reboot. This saves the **entire current firmware configuration**, including other unsaved changes. Apply alone only updates the running configuration.

Failure and rollback paths are tested against simulated firmware. The new form and actual outage failover have not yet been verified on hardware. `pass` does not prove fallback works; policies and routes also matter. These CLI commands and a `pass` state were previously checked on Netcraze Giga NC-1012, NetcrazeOS 5.1.5.

## Controls and names (v0.7.0)

Service controls start or stop the whole VPN service. Tunnel cards show individual profiles. Start and stop buttons are disabled when the corresponding action is unnecessary. Disabling autostart does not stop VPN; use Stop separately.

Connected means the service is started, the engine responds and that interface's PingCheck reports `pass`. Disconnected means the service is stopped, the engine is unavailable or PingCheck reports `fail`. Missing results show Connection not verified. The panel refreshes every 15 seconds in addition to the check's own delay. A successful check of one address does not guarantee access to all websites.

Rename changes the display name in the panel and the Netcraze interface description. Names allow 1–64 Latin letters, digits, spaces, dots, dashes or underscores. The profile filename and OpkgTun identifier remain unchanged; keep using the original filename for imports. Names are stored in `/opt/etc/awg3/names/` and reapplied at service startup. The native `connection-type.OpkgTun` type label is unchanged.

## Multiple tunnels (v0.7.0)

- **Overview** contains only each tunnel's name and connection status.
- **Tunnels → Add tunnel**: choose a unique Latin name, upload `.vpn`/`.txt`/`.conf` or paste a key, then Create and start. Existing tunnels keep running. Each needs a separate Amnezia client key; duplicate keys are rejected.
- **⚙ beside a tunnel** opens rename, key replacement, that profile's backups, PingCheck and deletion. Replacement is bound to the selected tunnel.
- **Start / Pause** affect that tunnel only. Pause persists across reboot and is respected by the watchdog. Importing into a paused tunnel does not start it. Whole-service startup retains individual pauses; resume using the tunnel's own button.
- **Log** only shows logs. Global service controls, autostart, watchdog, password and firmware configuration save are in **Settings**.

Each tunnel gets a separate `OpkgTunN` and AmneziaWG process. Use these interfaces for routing and device policies in Netcraze. The panel does not add default routes or assign devices automatically. Configure and verify each tunnel's routes and PingCheck, then save firmware configuration. The global save button also saves other pending router configuration changes.

Deletion requires confirmation. It stops the selected tunnel, terminates its verified process and removes its firmware interface without restarting neighbours. A private copy remains under `/opt/etc/awg3/backups/deleted/`. If deletion fails, the profile remains retryable, usually paused. After success choose **Settings → Save router configuration**. Adjust your policies and static routes separately if needed.

Deleted names and indexes remain reserved in `managed.tsv` so stale interface references cannot attach to another VPN. Use a new name for recreation. Index space is 0–99 including reservations; do not edit reservations without checking external references. Every additional userspace tunnel consumes RAM and CPU; a safe tunnel count on NC-1012 has not been measured.

If creation saves a profile but firmware rejects startup, the panel reports the error and retains the profile for editing, retry or deletion. Multi-tunnel operation has been tested against simulated firmware, not yet on physical NC-1012 hardware.

## Updating from the panel (v0.9.0)

Install v0.9.0 once using the existing `router/install-web.sh` procedure. Ensure the router has trusted CA certificates:

```sh
opkg update
opkg install ca-bundle
```

Open **Settings → Application update → Check for updates**. The panel shows the installed version and the latest stable release from `Parsefall/amnezia-netcraze`. Choose **Update** and confirm the selected version. The router downloads and installs the package itself. GitHub is contacted only when checking or installing an update.

Phases: download, archive and file verification, backup, installation, panel restart and HTTPS health check. Tunnel and settings mutations are blocked during updates. After restart the page reloads; sign in with the same password. Profiles, private keys, certificate, password, names, pause/autostart flags and routes are retained. VPN tunnels are not restarted; the watchdog is briefly stopped while its scripts are replaced.

The button updates the panel, importer and control scripts. If packaged `awg`/`amneziawg-go` binaries differ from installed ones or the installation format changes, the update is rejected **before files are replaced** and requires a manual procedure. Downgrades and same-version reinstalls are not supported by the button.

The router needs GitHub HTTPS access, a correct clock, panel dependencies and storage on `/opt` (the initial check requires at least 48 MiB, followed by a backup-space check). Archive sizes are bounded, tar links and unsafe paths are rejected, and SHA256 is verified before installation. Only this project's packaged Releases are downloaded, never arbitrary URLs or scripts from main.

If the replacement panel fails to start or file replacement fails, the updater attempts to restore and start the old version. Backups and logs are under `/opt/etc/awg3/updates/job-*/backup/` and `worker.log`; the update card shows the last result. Downloaded archives and staging files are cleaned up; backups remain.

Power loss/SIGKILL during replacement cannot guarantee automatic rollback. Such interrupted installation blocks further updates until manual recovery. Never remove an active `update.lock` or `service.lock`. For SSH recovery, first verify their recorded PIDs are no longer running, then use `backup/files.json` checksums and the saved files. VPN configuration and `web/settings.json` do not need restoration from an update because the updater never replaces them. Network errors require checking the clock, GitHub connectivity and `ca-bundle`; TLS verification is never disabled.

GitHub metadata fetching, filesystem installation/rollback tests and browser UI have been checked. Updating physical NC-1012 hardware has not yet been tested.
