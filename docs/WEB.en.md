# Router web panel

[Русский](WEB.md) | **English**

The v0.4.0 panel runs **on the router itself** through Entware. A computer or phone only provides the browser. It has its own HTTPS address; it is not a card in Netcraze's built-in Applications page. Includes Russian and English UI.

Features: file/key import, existing-profile replacement, start/stop of the whole VPN service, autostart, watchdog/inbox, handshake timestamps, traffic counters, PingCheck view, filtered log, backup restore and panel password change. Routing, device policies and PingCheck configuration stay in the firmware UI.

## Install over an existing project installation

Requires Entware and Amnezia Netcraze. For a new router, first follow [VPN installation](../INSTALL.en.md); you can then import a profile through the panel. Prior hardware testing is limited to Netcraze Giga NC-1012, hw 1210C000, aarch64, NetcrazeOS 5.1.5, kernel 4.9-ndm-5. **The new web panel has not yet been tested on physical hardware.**

1. Download `awg3-netcraze-arm64-userspace.tar.gz` from [v0.4.0](https://github.com/Parsefall/amnezia-netcraze/releases/tag/v0.4.0). In PC PowerShell from the download directory:

```powershell
scp -O -P 22 .\awg3-netcraze-arm64-userspace.tar.gz root@192.168.1.1:/opt/tmp/
ssh -p 22 root@192.168.1.1
```

2. In the **router's Entware SSH shell**:

```sh
opkg update
opkg install python3-light python3-codecs python3-openssl python3-email python3-urllib python3-logging openssl-util
mkdir -p /opt/tmp/awg3-v040
tar -xzf /opt/tmp/awg3-netcraze-arm64-userspace.tar.gz -C /opt/tmp/awg3-v040
sh /opt/tmp/awg3-v040/awg3-userspace/router/install-web.sh
```

Python modules are split into packages in [ARM64 Entware](https://bin.entware.net/aarch64-k3.10/). No pip or third-party Python library is required. The installer checks imports/checksums, updates import scripts with backups, and installs the panel. Engine binaries/profiles are retained; VPN and routes are not restarted or changed.

3. Create your **panel password** (12–128 characters) and LAN binding:

```sh
/opt/bin/python3 /opt/lib/awg3/web/server.py --setup --bind 192.168.1.1 --network 192.168.1.0/24 --port 8088
/opt/etc/init.d/S101awg3-web enable
```

The hidden password prompt is separate from root/firmware credentials. Adjust both address and subnet to your actual LAN. Wildcard/public binding is prohibited. If 8088 is occupied, choose another free port above 1023.

4. Open **https://192.168.1.1:8088** from the configured subnet. Exact IP/port matching is enforced; domain/CrazeDNS access is unsupported.

Setup creates a local self-signed certificate, so the browser will show a trust warning. Compare its SHA256 fingerprint against setup output before trusting it. Display the fingerprint again with:

```sh
/opt/bin/openssl x509 -in /opt/etc/awg3/web/cert.pem -noout -fingerprint -sha256
```

Keep this a home-LAN service: do not expose it using port forwarding or a public reverse proxy. Subnet checks do not replace guest-network isolation. Certificate lifetime is 825 days; rerun setup and restart the panel to renew it.

## Everyday use

- Profiles: use the existing basename **without .conf** (`pars` for `pars.conf`), select one file or paste a key, then Validate and apply. Unknown targets are rejected while VPN runs; new profiles can be imported when stopped.
- Import keeps the same OpkgTun, routes, policies and priority. See [router import](ROUTER-IMPORT.en.md) for format/rollback limitations. Export DNS is omitted, IPv6 removed, absent MTU defaults to 1280.
- Verify a fresh handshake, PingCheck and traffic after server migration. An available engine does not prove VPN connectivity. Update any manual exception route for the old Endpoint separately.
- Start/stop controls the **whole service**. Disable and stop VPN removes autostart and stops VPN.
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
