# Router routing integration

[Русский](ROUTING.md) | **English**

The application creates a separate `OpkgTunN` interface for each tunnel. It can be used in the router's native connection, routing and access-policy settings.

Creating and starting a tunnel does not assign devices or add a default route. Select the tunnel in the firmware interface and configure how it is used through the router's settings. AmneziaWG AllowedIPs does not replace firmware routing configuration.

Replacing a key in an existing tunnel retains its interface identifier and associations. After deleting a tunnel, check its related firmware settings. Save firmware configuration after network changes.

The application handles IPv4; IPv6 VPN routing is not implemented. DNS settings in exports imported through the panel are not applied automatically.

Configure [PingCheck](HEALTHCHECK.en.md) separately for each tunnel.

## Backup tunnel (0.10.0)

Open **Tunnels → ⚙ → Backup tunnel**, choose another connection and save. IP/domain lists and device assignments remain in Netcraze; the panel reads existing firmware rules, without asking you to duplicate them. The choice is saved on the router's storage automatically.

Both tunnels must be running with separate client keys and assigned PingCheck profiles. The backup's AllowedIPs must cover the routed IPv4 networks; DNS groups and policy memberships require `0.0.0.0/0`. Every 10 seconds a background worker checks for primary `fail` and backup `pass`. Unknown status is not success. Manual pause and whole-service stop are not outages. Original routing returns after 30 seconds of stable primary `pass`. The browser can be closed; the panel service must remain running.

Supported firmware rules: direct `ip route … OpkgTunN`, `ip policy NAME route … OpkgTunN`, `dns-proxy route object-group NAME OpkgTunN`, and explicit `ip policy NAME permit global OpkgTunN order N` memberships. Networks, DNS groups, exclusive-route flags and other policy members are retained. This is not an arbitrary interface-level packet redirect: implicit default/global priorities, unordered policy memberships, additional IP gateways, IPv6, custom iptables/ip rules and unknown command forms are not automatically migrated. Unsupported rules referencing the source cause an error. Readback verifies firmware configuration, not actual client packet delivery.

VPN engines and PingCheck stay running. Existing connections may break when the external IP changes. If both tunnels fail, original routing is restored, including any existing WAN fallback permissions; use native exclusive routes if bypass must be prohibited.

Choices live in `/opt/etc/awg3/failover.json`; `/opt/etc/awg3/failover-journal.json` contains affected rules before/after temporary changes, not VPN keys. It is written before mutations, retained if recovery cannot be verified, and used to recover interrupted transactions after restart. A normal panel shutdown restores routing. Do not delete the journal manually.

Select **No backup** to disable and restore. Disable backup before editing involved rules in Netcraze: conflicting external changes stop automatic rollback rather than overwrite the edit. Do not save firmware configuration from the router UI while backup routing is active, as that would persist temporary rules. The panel's own save action rejects this. Remove related backup assignments before deleting a tunnel or detaching its PingCheck.

Outage, failback, chains, partial command failures and restart recovery are tested with simulated firmware. Physical NC-1012 failover has not yet been verified.
