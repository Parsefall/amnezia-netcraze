# Routes and policies

[Русский](ROUTING.md) | **English**

## Only selected destinations through VPN

1. Keep the ISP first and the VPN below it in the default policy.
2. Keep the PC and the Home segment in the default policy.
3. Make sure there is no enabled user-defined default route pointing to the VPN.
4. Import your `.bat` using Routing → Upload, selecting the VPN interface. Do not execute the `.bat` on Windows.

Example format (documentation address; replace with the network you need):

```text
route ADD 192.0.2.0 MASK 255.255.255.0 0.0.0.0
```

Listed destinations use the tunnel; other traffic uses the ISP, subject to other existing routes. AWG AllowedIPs may remain `0.0.0.0/0`: it permits any IPv4 address inside the tunnel, while the routing table selects the actual path.

Amazon/Cloudflare lists include unrelated sites. Addresses change, and a filename does not guarantee coverage of a service. Automatic list updates are not implemented. Personal IP lists are not distributed with this project.

These routes do not control IPv6. A `curl -4` test verifies IPv4 only.

## An entire device through VPN

Keep the ISP first in the system policy. Assign one test device to a separate VPN policy. For a full tunnel, explicitly register the tunnel default route (use your interface index):

```sh
ndmc -c "ip route default OpkgTun0"
```

Check that the system default still uses the ISP and that the VPN Endpoint is not routed into its own tunnel:

```sh
ip -4 route show table all
ip -4 route get VPN_SERVER_IP
```

Replace VPN_SERVER_IP with the actual numerical IPv4 address. If the system default switched to VPN, restore the ISP priority. WAN addresses may change after reconnection; do not copy an old address from someone else's instructions.

A VPN-only policy intentionally has no fallback. For permitted WAN fallback, the ISP must also be included and availability monitoring is needed. To avoid IPv6 bypass, disable IPv6 on the test client or segment: this wrapper does not implement an IPv6 kill switch.

Home is a LAN segment, not the router itself. A client's explicit policy takes precedence over segment inheritance. Router services use system routing; individual routes and DNS bindings can affect the path.

## Returning to selected-IP routing

Return the device to the default policy with the ISP first. Disable the user-defined default route to VPN in the web interface, or remove it:

```sh
ndmc -c "no ip route default OpkgTun0"
```

On the test router this command once reported `file exists` even though the route disappeared. Inspect the resulting table rather than blindly repeating changes. Do not remove all interface routes if you have already imported a useful IP list.

## Testing from the PC

Use PowerShell with the local VPN application off and the intended policy assigned to this device:

```powershell
ping -4 -n 4 8.8.8.8
nslookup example.com
curl.exe -4 --connect-timeout 10 --max-time 20 https://example.com/
```

Check the external IP on the intended path. A successful ping to a DNS address with its own route does not prove a working full tunnel. With selected-IP routing, an IP-checking website may correctly show your ISP address.

Profile DNS servers are bound to the VPN with `ip name-server ... on OpkgTunN`. Firmware may create a dedicated DNS route: for example, 1.1.1.1 can continue using VPN while the ISP is first. Account for this when diagnosing failures, and test name resolution separately after a VPN outage.

[Official route import documentation](https://support.netcraze.ru/ultra/nc-1812/ru/15880-static-routing.html) (Russian).
