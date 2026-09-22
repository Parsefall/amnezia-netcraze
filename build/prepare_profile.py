"""Create an explicitly IPv4-only private copy. Never modify the source."""
import argparse
import ipaddress
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
parser.add_argument("--ipv4-only", action="store_true", required=True)
args = parser.parse_args()
if args.source.resolve() == args.destination.resolve():
    parser.error("Destination must differ from source")
lines = args.source.read_text(encoding="utf-8-sig").splitlines()
result = []
removed = 0
for line in lines:
    key, sep, value = line.partition("=")
    if sep and key.strip() == "AllowedIPs":
        networks = [ipaddress.ip_network(x.strip(), strict=False) for x in value.split(",")]
        ipv4 = [str(x) for x in networks if x.version == 4]
        removed += len(networks) - len(ipv4)
        if not ipv4:
            parser.error("No IPv4 AllowedIPs remain")
        line = "AllowedIPs = " + ", ".join(ipv4)
    result.append(line)
args.destination.parent.mkdir(parents=True, exist_ok=True)
# Exclusive create prevents accidentally replacing another private profile.
with args.destination.open("x", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(result) + "\n")
args.destination.chmod(0o600)
print(f"Private IPv4 copy written; removed {removed} IPv6 route(s). Original unchanged.")
