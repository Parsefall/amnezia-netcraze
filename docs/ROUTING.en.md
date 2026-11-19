# Router routing integration

[Русский](ROUTING.md) | **English**

The application creates a separate `OpkgTunN` interface for each tunnel. It can be used in the router's native connection, routing and access-policy settings.

Creating and starting a tunnel does not assign devices or add a default route. Select the tunnel in the firmware interface and configure how it is used through the router's settings. AmneziaWG AllowedIPs does not replace firmware routing configuration.

Replacing a key in an existing tunnel retains its interface identifier and associations. After deleting a tunnel, check its related firmware settings. Save firmware configuration after network changes.

The application handles IPv4; IPv6 VPN routing is not implemented. DNS settings in exports imported through the panel are not applied automatically.

Configure [PingCheck](HEALTHCHECK.en.md) separately for each tunnel.

## Backup tunnel (0.10.0)

Open **Tunnels → ⚙ → Backup tunnel**, choose another connection and save. IP/domain lists and device assignments remain in Netcraze; the panel reads existing firmware rules, without asking you to duplicate them. The choice is saved on the router's storage automatically.

Use separate client keys and assign PingCheck to each tunnel. The backup's AllowedIPs must cover the routed IPv4 networks, or the full IPv4 range for DNS groups and policy memberships.

Since 0.10.1 the panel switches routes when the primary fails PingCheck, its engine is unavailable, or Netcraze reports the interface down. The latter two conditions apply even when the PingCheck entry has disappeared. Selecting a backup requires a responding engine, an available firmware interface and a passing PingCheck. A temporary gap in observations preserves the active backup. Original routing returns after 30 seconds of stable primary availability or when the active backup is confirmed down and no further backup is available. The worker respects manual pauses and whole-service stops and runs every 10 seconds while the panel service is running.

Supported firmware rules: direct `ip route … OpkgTunN`, `ip policy NAME route … OpkgTunN`, `dns-proxy route object-group NAME OpkgTunN`, and explicit `ip policy NAME permit global OpkgTunN order N` memberships. Networks, DNS groups, exclusive-route flags and other policy members are retained. This is not an arbitrary interface-level packet redirect: implicit default/global priorities, unordered policy memberships, additional IP gateways, IPv6, custom iptables/ip rules and unknown command forms are not automatically migrated. Unsupported rules referencing the source cause an error. Readback verifies firmware configuration, not actual client packet delivery.

VPN engines and PingCheck stay running. Existing connections may break when the external IP changes. If both tunnels fail, original routing is restored, including any existing WAN fallback permissions; use native exclusive routes if bypass must be prohibited.

Choices live in `/opt/etc/awg3/failover.json`; `/opt/etc/awg3/failover-journal.json` contains affected rules before/after temporary changes, not VPN keys. It is written before mutations, retained if recovery cannot be verified, and used to recover interrupted transactions after restart. A normal panel shutdown restores routing. Do not delete the journal manually.

Select **No backup** to disable and restore. Disable backup before editing involved rules in Netcraze: conflicting external changes stop automatic rollback rather than overwrite the edit. Do not save firmware configuration from the router UI while backup routing is active, as that would persist temporary rules. The panel's own save action rejects this. Remove related backup assignments before deleting a tunnel or detaching its PingCheck.

Outage, failback, chains, partial command failures and restart recovery are tested with simulated firmware. Physical NC-1012 failover has not yet been verified.
