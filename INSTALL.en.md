# Installing Amnezia Netcraze

[Русский](INSTALL.md) | **English**

Install the application on your router, open the web panel and add an AmneziaWG client profile by uploading an export or pasting its full key.

## 1. Prerequisites

You need ARM64 (`aarch64`), Entware installed at `/opt`, root access to its SSH shell and `/dev/net/tun`. Tested hardware: Netcraze Giga NC-1012, revision 1210C000, NetcrazeOS 5.1.5, kernel 4.9-ndm-5. Other models have not been tested. Initial Entware setup is outside this guide.

Back up router configuration and keep the ISP first in the default policy until VPN connectivity is verified.

Create a **separate AmneziaWG client for the router** and prepare one of:

- a guest `.vpn` export containing an embedded AmneziaWG client configuration;
- a `.txt` file containing that client's full `vpn://…` key;
- the full `vpn://…` key to paste into the panel.

An existing native `.conf` is also accepted, but you do not need to generate one. Never share a client key between a PC and router or multiple tunnels.

Not every Amnezia key contains a client configuration: subscription keys, administrative exports without a client profile, and a bare PrivateKey are insufficient. If import reports a missing AWG profile, obtain an AmneziaWG client export from the server owner/provider. Automatic subscription retrieval is not implemented. Do not rename `.vpn` to `.conf`.

## 2. Download and copy

Download `awg3-netcraze-arm64-userspace.tar.gz` and its `.sha256` from the [latest release](https://github.com/Parsefall/amnezia-netcraze/releases/latest).

In **Windows PowerShell**, from your download directory:

```powershell
Get-FileHash .\awg3-netcraze-arm64-userspace.tar.gz -Algorithm SHA256
Get-Content .\awg3-netcraze-arm64-userspace.tar.gz.sha256
```

Compare the hashes before continuing.

```powershell
scp -O -P 22 .\awg3-netcraze-arm64-userspace.tar.gz root@192.168.1.1:/opt/tmp/
ssh -p 22 root@192.168.1.1
```

Adjust the IP and SSH port if necessary. Use the Entware shell (`~ #`), not the firmware CLI.

## 3. Install the engine and panel

These commands are for a **first installation** and run in the **router SSH shell**. For an existing installation, use the update section below.

```sh
opkg update
opkg install python3-light python3-codecs python3-openssl python3-email python3-urllib python3-logging openssl-util ca-bundle
mkdir -p /opt/tmp/awg3-setup
tar -xzf /opt/tmp/awg3-netcraze-arm64-userspace.tar.gz -C /opt/tmp/awg3-setup
cd /opt/tmp/awg3-setup/awg3-userspace
sh router/install.sh
sh router/install-web.sh
```

Continue only if each command succeeds. Installers verify internal checksums. The VPN is not started, no profile is imported and routing remains unchanged at this stage.

Set the panel password and your LAN parameters:

```sh
/opt/bin/python3 /opt/lib/awg3/web/server.py --setup --bind 192.168.1.1 --network 192.168.1.0/24 --port 8088
/opt/etc/init.d/S101awg3-web enable
```

Adjust the address/subnet to your LAN. The separate panel password is 12–128 characters and entered twice without echo. Record the displayed certificate fingerprint.

## 4. Add a tunnel in your browser

1. Open **http://192.168.1.1:8088** or **https://192.168.1.1:8088** from the LAN. HTTP transmits passwords and profiles without encryption. The self-signed certificate triggers a browser warning; compare its fingerprint with setup output. See the [panel guide](docs/WEB.en.md).
2. Sign in with your panel password.
3. Open **Tunnels → Add tunnel**.
4. Enter a unique Latin name, choose a `.vpn`/`.txt` file **or** paste the full key.
5. Click **Create and start**.

The application validates and converts the export, then saves its internal configuration with restricted permissions. You do not create or edit `.conf` manually. Add more tunnels the same way, with a separate client key for each.

## 5. Routing, checks and autostart

Creating a tunnel does not automatically route all Internet traffic through it. Choose a [routing setup](docs/ROUTING.en.md) in the router's native interface.

Enable [PingCheck](docs/HEALTHCHECK.en.md) in that tunnel's settings (⚙). Check status, external IP and website access from a device assigned VPN routing, with its own VPN application disabled.

Enable VPN autostart in panel Settings. It is global; individually paused tunnels remain paused. Watchdog is separately enabled and recovers the local engine; PingCheck tests connectivity through the tunnel. Actual outage failover has not yet been tested on hardware.

Save firmware configuration after changing routes and PingCheck. The PingCheck save button saves **all current router configuration**, including other pending changes. Verify connectivity again after reboot. The panel has separate autostart.

## Replacing a key or server

Open **Tunnels → ⚙ for the target tunnel → Replace VPN key**, upload a new `.vpn`/`.txt` or paste its key, then apply it. Replace the existing tunnel's key instead of creating another tunnel when you want to retain routing and policy associations.

The interface identifier and associations are retained; check traffic after replacement. Update any manually created route to the old server endpoint separately. The new profile must permit your destinations in AllowedIPs.

## Updating the application

From v0.8.0, use **Settings → Application update → Check → Update**. The router downloads and verifies compatible releases and creates a backup. Sign in again after the panel restarts. See [panel updating](docs/WEB.en.md) for rollback and limitations.

For an older panel, copy and extract the new package, install the dependencies from step 3 and run **only `sh router/install-web.sh`**, then reload with Ctrl+F5. Existing passwords, certificates and profiles are retained; do not repeat `--setup`.

Releases changing VPN binaries require manual updating. Move clients back to the ISP and back up profiles/settings. Run `/opt/etc/init.d/S99awg3 disable`, then reboot: stopping the service retains TUN processes, and the installer refuses to replace a running engine. After reboot run both installers, check routes, start the required tunnels and re-enable autostart.

## Alternative tools and removal

[SSH/inbox import](docs/ROUTER-IMPORT.en.md) and the [offline desktop converter](docs/CONVERTER.en.md) are optional alternatives, not prerequisites for the panel workflow.

To uninstall, move clients back to the ISP and disable your VPN routes. Run `/opt/etc/init.d/S99awg3 disable`, then `/opt/etc/init.d/S99awg3 stop`. The package's `sh router/uninstall.sh` preserves profiles, binaries, backups and NDMS objects; it is not a full network rollback. Do not restore the incompatible legacy `amneziawg.ko`.
