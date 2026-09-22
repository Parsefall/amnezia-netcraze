# Troubleshooting

[Русский](TROUBLESHOOTING.md) | **English**

| Symptom | What to check |
|---|---|
| SSH Connection refused on 222 | The tested router used port 22 for Entware SSH. Use your actual port. |
| SSH disconnected after reboot | Reconnect with ssh -p 22 root@192.168.1.1. |
| curl.exe: not found | A Windows command was entered in router SSH. Enter exit or open another PowerShell tab. |
| Handshake works but traffic does not | Separate profiles for PC/router, Endpoint routed through ISP, actual ping and HTTPS tests. |
| Green indicator but websites fail | Configure Ping Check and test traffic, not just interface state. |
| VPN first causes connectivity loss | Put ISP first, test one device in a separate policy. Fallback is not yet guaranteed. |
| VPN priority returns after reboot | That priority was saved. Saving NDMS and enabling the service are separate operations. |
| No default route in full-tunnel mode | Add it explicitly using ROUTING. Selected-IP mode does not need it. |
| ip: invalid argument 29999 to table | The router uses BusyBox ip, which rejected large table IDs. Do not substitute an arbitrary table without checking for conflicts. |
| iptables: not found | Entware utility availability does not indicate whether NAT exists. Use firmware diagnostics. |
| Unknown symbol crypto_chacha_init | The old kernel module is incompatible. This project uses userspace and does not need it. |
| NDMS error with exit code 0 | Inspect output too, including error[code]. Release scripts account for this. |
| Ping Check argument parse error | Create the profile with a separate command first. |
| Ping Check has no assigned profile | Bind the profile before no ping-check restart. |
| Installer refuses an engine update | Disable and reboot: stop alone keeps the TUN process alive. |

## Basic diagnostics — router SSH

```sh
/opt/etc/init.d/S99awg3 status
ndmc -c "show ping-check"
ip -4 route show table all
ip -4 rule show
```

An early build exposed HeaderProtectionKey in status. Filter its output before sharing: `... status | sed '/header protection key:/d'`. The released version hides it. Do not publish showconf, private profiles, a complete running-config, or unreviewed logs. Status can also include public IPs and public keys.

A router's successful ping may travel through the ISP. A PC test with its own VPN application running tests a different tunnel. Both caused misleading conclusions during initial setup.

## Memory

```sh
free
p=$(cat /var/run/awg3/opkgtun0.pid)
grep -E '^(Name|VmRSS|VmHWM|VmSize|Threads):' "/proc/$p/status"
```

Use your interface index. VmRSS is current resident memory; VmHWM is the peak since startup; VmSize is virtual address space, not physical RAM usage.

One NC-1012 observation: RSS 47168 KiB (~46 MiB), HWM 231748 KiB (~226 MiB), 16 threads, ~233 MiB available system memory, no swap used. This is not a resource guarantee or load test. Compare RSS under similar loads; a memory leak has not been established.

## service.lock

Locks are not automatically taken over. Do not remove a live service's lock. Check its PID and process; if downtime is acceptable, disable autostart and reboot. Service: started is a startup marker, not proof that every tunnel works.
