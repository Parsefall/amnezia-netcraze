#!/usr/bin/env python3
"""Offline extraction of Amnezia guest exports; never contacts a server.

Reference: amnezia-client 94b51df24790bf52427afe82d81c87a95460bdfd,
exportController.cpp and models/protocols/awgProtocolConfig.cpp.
"""
import argparse
import base64
import binascii
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import zlib

MAX_INPUT = 4 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
INTERFACE = set('Address DNS MTU PrivateKey ListenPort FwMark Jc Jmin Jmax S1 S2 S3 S4 H1 H2 H3 H4 I1 I2 I3 I4 I5 HeaderProtectionKey ContentPaddingAddition RekeyAfterTime RekeyTimeout RejectAfterTime KeepaliveTimeout MaxHandshakeAttempts RandomTrailers DisableCookies'.split())
PEER = set('PublicKey PresharedKey AllowedIPs Endpoint PersistentKeepalive'.split())


class ConversionError(ValueError):
    """Messages must never contain input fragments or secret values."""


def load_json(text):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ConversionError('Duplicate JSON fields; export the profile again.')
            result[k] = v
        return result
    try:
        value = json.loads(text, object_pairs_hook=unique)
    except (ValueError, RecursionError):
        raise ConversionError('Invalid or excessively nested JSON; export the profile again.') from None
    if not isinstance(value, dict):
        raise ConversionError('Expected one Amnezia export object, not a backup or list.')
    return value


def quncompress(data):
    if len(data) < 6:
        raise ConversionError('Truncated Amnezia data.')
    expected = int.from_bytes(data[:4], 'big')
    if not 0 < expected <= MAX_JSON:
        raise ConversionError('Invalid or oversized decompressed data.')
    try:
        stream = zlib.decompressobj()
        decoded = stream.decompress(data[4:], MAX_JSON + 1)
    except zlib.error:
        raise ConversionError('Invalid compressed Amnezia data.') from None
    if len(decoded) != expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise ConversionError('Damaged, oversized, or trailing compressed data.')
    return decoded


def decode_export(data):
    if not data or len(data) > MAX_INPUT:
        raise ConversionError('Input is empty or exceeds the 4 MiB limit.')
    try:
        text = data.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        text = None
    if text is not None and (text.startswith('[Interface]') or text.startswith(('#', ';'))):
        return text
    if text is not None and text.startswith('{'):
        return load_json(text)
    if text is not None and (text.startswith('vpn://') or re.fullmatch(r'[A-Za-z0-9_+/=\s-]+', text)):
        encoded = text[6:] if text.startswith('vpn://') else text
        encoded = re.sub(r'\s+', '', encoded)
        try:
            raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        except (ValueError, binascii.Error):
            raise ConversionError('Invalid vpn:// key encoding.') from None
        if raw.lstrip().startswith(b'{'):
            decoded = raw
        else:
            decoded = quncompress(raw)
    else:
        decoded = quncompress(data)
    try:
        return load_json(decoded.decode('utf-8-sig'))
    except UnicodeDecodeError:
        raise ConversionError('The decoded export is not UTF-8 JSON.') from None


def extract_profile(value, index=None):
    if isinstance(value, str):
        if index not in (None, 1):
            raise ConversionError('This native file contains only one profile.')
        return value
    containers = value.get('containers')
    if not isinstance(containers, list):
        raise ConversionError('No offline AWG client profile. A subscription/API key needs a .conf from the provider dashboard; a full-access key needs a separate guest AWG export in AmneziaVPN.')
    profiles = []
    missing = False
    for container in containers:
        if not isinstance(container, dict) or not isinstance(container.get('awg'), dict):
            continue
        last = container['awg'].get('last_config')
        if not last:
            missing = True
            continue
        # Official format uses a JSON string; accept an already decoded object too.
        if isinstance(last, str):
            last = load_json(last)
        if not isinstance(last, dict) or not isinstance(last.get('config'), str) or not last['config'].strip():
            raise ConversionError('AWG export has no native client configuration; export a guest profile in AmneziaVPN.')
        profiles.append(last['config'])
    if not profiles:
        if missing:
            raise ConversionError('AWG settings exist but no client profile. Full-access exports do not include client keys; create a separate guest AWG profile.')
        raise ConversionError('No AmneziaWG client configuration found. Other protocols cannot be converted to AWG.')
    if index is None:
        if len(profiles) != 1:
            raise ConversionError('Multiple AWG profiles found. Export one profile or select --profile-index N (starting at 1).')
        return profiles[0]
    if not 1 <= index <= len(profiles):
        raise ConversionError('Profile index is out of range.')
    return profiles[index - 1]


def validate_key(value):
    try:
        valid = len(base64.b64decode(value, validate=True)) == 32
    except (ValueError, binascii.Error):
        valid = False
    if not valid:
        raise ConversionError('A cryptographic key is not a valid 32-byte Base64 value.')


def prepare_native(text, ipv4_only=False):
    sections = {'Interface': {}, 'Peer': {}}
    current = None
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue  # Do not copy metadata/comments that may contain subscription keys.
        if any(ord(c) < 32 and c != '\t' for c in line):
            raise ConversionError('Control characters in the profile are not supported.')
        if line.startswith('['):
            if line not in ('[Interface]', '[Peer]'):
                raise ConversionError('Unsupported configuration section.')
            current = line[1:-1]
            if current in seen or (current == 'Peer' and 'Interface' not in seen):
                raise ConversionError('Exactly one Interface followed by one Peer is supported.')
            seen.add(current)
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if key == 'PreSharedKey':
            key = 'PresharedKey'
        if current is None or not separator or not value:
            raise ConversionError('Malformed or empty profile setting.')
        allowed = INTERFACE if current == 'Interface' else PEER
        if key not in allowed or key in sections[current]:
            raise ConversionError('Unsupported or duplicate profile setting. Shell hooks such as PostUp are not accepted.')
        sections[current][key] = value
    for section, required in [('Interface', ('PrivateKey', 'Address')), ('Peer', ('PublicKey', 'AllowedIPs', 'Endpoint'))]:
        if any(k not in sections[section] for k in required):
            raise ConversionError('The profile is missing required client connection fields.')
    removed = 0
    for section, key, parser in [('Interface', 'Address', ipaddress.ip_interface), ('Interface', 'DNS', ipaddress.ip_address), ('Peer', 'AllowedIPs', ipaddress.ip_network)]:
        fields = sections[section]
        if key not in fields:
            continue
        try:
            values = [parser(v.strip()) for v in fields[key].split(',')]
        except ValueError:
            raise ConversionError('Invalid Address, DNS, or AllowedIPs. DNS must contain IP addresses.') from None
        v4 = [v for v in values if v.version == 4]
        if len(v4) != len(values) and not ipv4_only:
            raise ConversionError('IPv6 is present. Select IPv4-only conversion for this router wrapper.')
        removed += len(values) - len(v4)
        if key == 'Address' and len(v4) != 1:
            raise ConversionError('Exactly one IPv4 interface address is required.')
        if not v4:
            if key == 'DNS':
                del fields[key]
                continue
            raise ConversionError('No IPv4 routes remain.')
        fields[key] = ', '.join(str(v) for v in v4)
    for section, keys in [('Interface', ('PrivateKey', 'HeaderProtectionKey')), ('Peer', ('PublicKey', 'PresharedKey'))]:
        for key in keys:
            if key in sections[section]:
                validate_key(sections[section][key])
    mtu = sections['Interface'].get('MTU')
    if mtu is not None and (len(mtu) > 4 or not mtu.isdecimal() or not 576 <= int(mtu) <= 9000):
        raise ConversionError('MTU must be between 576 and 9000.')
    endpoint = sections['Peer']['Endpoint']
    match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9.-]*):(\d{1,5})', endpoint)
    if not match or not 1 <= int(match[2]) <= 65535:
        raise ConversionError('Endpoint must be an IPv4 address or hostname followed by a valid port.')
    # Preserve all supplied AWG parameters, including I1-I5, without guessing values.
    result = '\n\n'.join('['+section+']\n'+'\n'.join(k+' = '+v for k,v in fields.items()) for section,fields in sections.items())+'\n'
    return result, removed


def convert(data, ipv4_only=False, profile_index=None):
    return prepare_native(extract_profile(decode_export(data), profile_index), ipv4_only)


def read_input(path):
    with Path(path).open('rb') as f:
        return f.read(MAX_INPUT + 1)


def save_private(path, text):
    path = Path(path)
    if path.suffix.lower() != '.conf':
        raise ConversionError('Output filename must end in .conf.')
    # O_EXCL also refuses existing symlinks. No overwrite option by design.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group()
    src.add_argument('--input', type=Path, help='.vpn, text key file, or native .conf')
    src.add_argument('--paste', action='store_true', help='Read a key at a hidden prompt, not in command history')
    parser.add_argument('--output', type=Path, default=Path('router.conf'))
    parser.add_argument('--ipv4-only', action='store_true', help='Explicitly remove IPv6 Address/DNS/routes')
    parser.add_argument('--profile-index', type=int)
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--lang', choices=['ru','en'], default='ru', help='GUI language')
    args = parser.parse_args()
    if args.gui or (not args.input and not args.paste):
        try:
            from converter_gui import run
        except ImportError:
            print("ERROR: GUI needs tkinter. Use --input/--paste or install Python with tkinter.", file=sys.stderr)
            return 1
        run(args.lang)
        return 0
    try:
        if args.paste:
            if not sys.stdin.isatty():
                raise ConversionError('Use --input for files or --paste in an interactive terminal.')
            data = getpass.getpass('Paste vpn:// key (hidden): ').encode('utf-8')
        else:
            data = read_input(args.input)
        text, removed = convert(data, args.ipv4_only, args.profile_index)
        save_private(args.output, text)
        print('Saved private .conf. Removed IPv6 entries:', removed)
        print('Source unchanged. Use this client profile on one device only.')
        return 0
    except ConversionError as exc:
        print('ERROR:',str(exc),file=sys.stderr)
    except FileExistsError:
        print('ERROR: Output already exists. Choose a new filename.',file=sys.stderr)
    except (OSError, UnicodeError):
        print('ERROR: Unable to read input or write output; check paths and permissions.',file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
