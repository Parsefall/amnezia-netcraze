"""Build an allowlisted deployment archive; personal profiles and .ko are excluded."""
from pathlib import Path
import hashlib
import io
import json
import struct
import tarfile

root = Path(__file__).resolve().parent.parent
names = [
    "README.md", "INSTALL.md", "ARCHITECTURE.md", "VALIDATION.md",
    "NOTICE.md", "CHANGELOG.md", "docs/ROUTING.md", "docs/HEALTHCHECK.md",
    "docs/TROUBLESHOOTING.md", "docs/BUILD.md", "build/prepare_profile.py",
    "build/patches/002-go-tun-padding-refresh.patch",
    "router/install.sh", "router/uninstall.sh",
    "router/opt/bin/awg3-split-config",
    "router/opt/etc/init.d/S99awg3",
    "router/opt/etc/init.d/S100awg3-watchdog",
    "router/opt/etc/awg3/conf/awg3_example.conf",
    "prebuilt/kn-1012/awg", "prebuilt/kn-1012/amneziawg-go",
    "prebuilt/kn-1012/BUILD-INFO.json",
    "prebuilt/kn-1012/LICENSE-amneziawg-go",
    "prebuilt/kn-1012/COPYING-amneziawg-tools",
]
metadata = json.loads((root/"prebuilt/kn-1012/BUILD-INFO.json").read_text(encoding="utf-8"))
for name in ("awg", "amneziawg-go"):
    data = (root / "prebuilt/kn-1012" / name).read_bytes()
    section = "engine" if name == "amneziawg-go" else "cli"
    assert hashlib.sha256(data).hexdigest() == metadata[section]["sha256"], "Update BUILD-INFO after rebuilding " + name
    assert data[:5] == b"\x7fELF\x02" and struct.unpack_from("<H", data, 18)[0] == 183, name
    if name == "amneziawg-go":
        offset = struct.unpack_from("<Q", data, 32)[0]
        size, count = struct.unpack_from("<HH", data, 54)
        assert all(struct.unpack_from("<I", data, offset + size*i)[0] != 3 for i in range(count)), "Dynamic interpreter found"
payload = {name: (root/name).read_bytes() for name in names}
manifest = "".join(hashlib.sha256(data).hexdigest()+"  "+name+"\n" for name, data in sorted(payload.items()))
(root/"SHA256SUMS").write_text(manifest, encoding="ascii", newline="\n")
payload["SHA256SUMS"] = manifest.encode()
destination = root/"outputs/awg3-netcraze-arm64-userspace.tar.gz"
destination.parent.mkdir(exist_ok=True)
with tarfile.open(destination, "w:gz") as archive:
    for name, data in sorted(payload.items()):
        info = tarfile.TarInfo("awg3-userspace/"+name)
        info.size = len(data)
        info.mtime = 0
        info.mode = 0o755 if name.startswith("router/") and not name.endswith(".conf") or name in ("prebuilt/kn-1012/awg", "prebuilt/kn-1012/amneziawg-go") else 0o644
        archive.addfile(info, io.BytesIO(data))
digest = hashlib.sha256(destination.read_bytes()).hexdigest()
destination.with_suffix(destination.suffix+".sha256").write_text(digest+"  "+destination.name+"\n", encoding="ascii")
with tarfile.open(destination) as archive:
    assert len(archive.getmembers()) == len(payload)
    for member in archive:
        assert archive.extractfile(member).read() == payload[member.name.removeprefix("awg3-userspace/")]
print(json.dumps({"archive":str(destination),"sha256":digest,"files":len(payload)}, indent=2))
