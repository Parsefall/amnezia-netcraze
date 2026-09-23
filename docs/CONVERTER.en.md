# Convert .vpn / vpn:// to router.conf

This is an optional desktop tool. The [panel installation](../INSTALL.en.md) does not require it: upload `.vpn`/`.txt` or paste a key directly in your browser.

[Русский](CONVERTER.md) | **English**

To avoid conversion on a PC, use [router import](ROUTER-IMPORT.en.md): it accepts .vpn or .txt and can automatically replace an existing profile.

The converter runs **offline**. It extracts an existing AmneziaWG client profile from an Amnezia guest export. Secrets are not uploaded, printed to the console, or passed as command-line arguments.

## Easy Windows workflow

1. Download `amnezia-netcraze-converter.zip` from the [latest release](https://github.com/Parsefall/amnezia-netcraze/releases/latest) and extract the whole archive. The installation tar.gz also includes the converter.
2. Install **Python 3.10+ with tkinter**. The standard Windows installer offers Tcl/Tk support. No third-party Python packages or pip are needed.
3. Run `python tools/convert_profile.py --gui --lang en`. Double-clicking `convert-profile.cmd` opens the Russian interface.
4. Select a `.vpn` file **or** paste a `vpn://…` key into the window. Use only one source.
5. Keep IPv4 only selected for this router and click Save router.conf. Choose a new filename if the file already exists.
6. Copy the resulting file to the router using step 3 of the [installation guide](https://github.com/Parsefall/amnezia-netcraze/blob/main/INSTALL.en.md).

Without tkinter, use the CLI. On Windows, folder permissions also determine file privacy: save to a private local folder, not a shared or synchronized one.

## Command line

In PowerShell or a PC terminal, from the extracted folder:

```powershell
python tools/convert_profile.py --input amnezia_config.vpn --output router.conf --ipv4-only
```

For a text key:

```powershell
python tools/convert_profile.py --paste --output router.conf --ipv4-only
```

Paste the key **at the application's hidden prompt**, not into the command itself. Alternatively, save it to a local .txt file and use --input. Multiple embedded AWG profiles require --profile-index N, starting at 1; GUI users must export one profile or use the CLI. An ambiguous profile is never selected automatically.

## Supported data

- A `.vpn` containing a `vpn://` key encoded with Base64URL and Qt qCompress (4-byte length plus zlib), or the same key as text.
- Uncompressed JSON, Base64 JSON, and binary qCompress exports.
- `containers[].awg.last_config` as a JSON string or object containing a complete native `config`.
- An existing native `.conf` for validation and IPv4 preparation.

Supplied AWG parameters, including I1–I5 and HeaderProtectionKey, are preserved. Required fields, structure, keys, addresses, Endpoint, and wrapper compatibility are checked; awg performs final protocol validation. Shell hooks such as PostUp and unknown fields are rejected, never executed. Comments are omitted to avoid copying subscription keys from metadata.

--ipv4-only explicitly removes IPv6 from Address, DNS, and AllowedIPs. One IPv4 Address and at least one IPv4 AllowedIPs entry are required; IPv6-only DNS is removed. Without the option, IPv6 produces an error. The converter does not change router routes or convert AWG 2.0 into 3.1.

## What cannot be extracted offline

**Not every key contains a client profile.** A Premium subscription/API key may contain only service access information; a full-access server export may omit client keys. The converter then explains that you need a .conf from the dashboard or a separate guest AWG export from AmneziaVPN. It does not sign in to a dashboard or connect to the server over SSH.

Other protocols, multiple peers, and damaged files are rejected. Decompression is size-limited. Input is unchanged and existing output files are never overwritten. On POSIX, new files are created with mode 0600.

**Conversion does not create a new client or new keys.** Do not use the original profile on a PC and its converted copy on a router simultaneously. Create separate guest access for the router first.

The format was checked against official [exportController](https://github.com/amnezia-vpn/amnezia-client/blob/94b51df24790bf52427afe82d81c87a95460bdfd/client/core/controllers/selfhosted/exportController.cpp) and [AwgProtocolConfig](https://github.com/amnezia-vpn/amnezia-client/blob/94b51df24790bf52427afe82d81c87a95460bdfd/client/core/models/protocols/awgProtocolConfig.cpp). Tests use synthetic profiles; this converter version has not yet processed the user's real export. The graphical window has not been manually tested.
