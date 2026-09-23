# Router routing integration

[Русский](ROUTING.md) | **English**

The application creates a separate `OpkgTunN` interface for each tunnel. It can be used in the router's native connection, routing and access-policy settings.

Creating and starting a tunnel does not assign devices or add a default route. Select the tunnel in the firmware interface and configure how it is used through the router's settings. AmneziaWG AllowedIPs does not replace firmware routing configuration.

Replacing a key in an existing tunnel retains its interface identifier and associations. After deleting a tunnel, check its related firmware settings. Save firmware configuration after network changes.

The application handles IPv4; IPv6 VPN routing is not implemented. DNS settings in exports imported through the panel are not applied automatically.

Configure [PingCheck](HEALTHCHECK.en.md) separately for each tunnel. Failover also depends on firmware policies: PingCheck status alone does not prove that switching to another connection has been tested.
