# Ping Check: monitoring traffic through the VPN

[Русский](HEALTHCHECK.md) | **English**

A green interface and a recent handshake do not guarantee Internet access. The package watchdog checks local UAPI availability, not packet delivery. Use NDMS's built-in Ping Check to monitor connectivity.

## Verified command sequence

Replace OpkgTun0 with your interface. Run these commands in the **router's SSH shell**. First run `ndmc -c "show ping-check"`; do not replace an existing profile without understanding its purpose. Use different profile names for multiple tunnels.

```sh
ndmc -c "ping-check profile AWG3Check"
ndmc -c "ping-check profile AWG3Check host 1.1.1.1"
ndmc -c "ping-check profile AWG3Check mode icmp"
ndmc -c "ping-check profile AWG3Check update-interval 10"
ndmc -c "ping-check profile AWG3Check timeout 3"
ndmc -c "ping-check profile AWG3Check max-fails 3"
ndmc -c "ping-check profile AWG3Check min-success 2"
ndmc -c "interface OpkgTun0 ping-check profile AWG3Check"
ndmc -c "interface OpkgTun0 no ping-check restart"
```

**Create the profile in a separate first command.** Otherwise the tested firmware returned `argument parse error`. Run `no ping-check restart` **after binding** the profile, or it returns `has no assigned profile`.

Stop on any error. After 30–60 seconds:

```sh
ndmc -c "show ping-check"
```

On the NC-1012, the output showed `name: OpkgTun0`, `ignore-fail: no`, `status: pass`, an increasing successcount, and failcount: 0. After checking, save:

```sh
ndmc -c "system configuration save"
```

The interval is 10 seconds, timeout 3 seconds, with thresholds of 3 failures and 2 successes. This does not guarantee switching in exactly 30 seconds. Failure of the sole probe destination can also mark the tunnel unavailable. Probe a destination beyond the tunnel: reachability of the Endpoint through the ISP does not prove VPN connectivity.

## Validation limits

Only **successful probes** were verified on the router; the owner deferred a simulated outage. Indicator changes on failure, absence of false success through WAN, client traffic failover, and recovery remain unverified. Test all of them while retaining local access and a prepared method to restore the VPN.

Taking the TUN interface down is not a sufficient test of a hung VPN: it tests administrative shutdown. Do not stop a shared remote VPN server just to test one client.

The policy must allow the ISP for fallback. **Exclusive static routes prohibit bypass.** Also check whether imported routes become inactive when Ping Check fails. A passing health check does not guarantee failover for arbitrary routing tables.

## Removing the binding

```sh
ndmc -c "interface OpkgTun0 no ping-check profile AWG3Check"
```

Use your own names, check show ping-check, and save the configuration. The unbound profile can remain unused.

[Netcraze documentation](https://support.netcraze.ru/4g/nc-1213/ru/17902-ping-check-fine-tuning.html) (Russian).
