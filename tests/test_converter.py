import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import convert_profile as c

KEY1 = base64.b64encode(bytes(range(32))).decode()
KEY2 = base64.b64encode(bytes(range(32, 64))).decode()
NATIVE = f'''[Interface]
Address = 10.0.0.2/32
DNS = 1.1.1.1
MTU = 1280
PrivateKey = {KEY1}
Jc = 6
S1 = 12
S2 = 12
S3 = 12
S4 = 12
I1 = <r 2><b 0x85800001>
HeaderProtectionKey = {KEY2}
RandomTrailers = on
DisableCookies = on

[Peer]
PublicKey = {KEY2}
PresharedKey = {KEY1}
Endpoint = 192.0.2.1:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25-35
'''


def export(native=NATIVE):
    return {'containers': [{'container': 'amnezia-awg', 'awg': {'last_config': json.dumps({'config': native, 'client_priv_key': KEY1})}}]}


def qt(data):
    return len(data).to_bytes(4, 'big') + zlib.compress(data, 8)


def url(obj):
    return b'vpn://' + base64.urlsafe_b64encode(qt(json.dumps(obj).encode())).rstrip(b'=')


class ConverterTests(unittest.TestCase):
    def test_official_export_encodings(self):
        raw = json.dumps(export()).encode()
        forms = [url(export()), raw, qt(raw), base64.urlsafe_b64encode(qt(raw)), b'vpn://'+base64.urlsafe_b64encode(raw), b'\xef\xbb\xbf'+url(export())+b'\r\n']
        for data in forms:
            with self.subTest(form=data[:8]):
                text, removed = c.convert(data)
                self.assertEqual(text, NATIVE)
                self.assertEqual(removed, 0)

    def test_object_last_config(self):
        data=export();data['containers'][0]['awg']['last_config']={'config':NATIVE}
        self.assertEqual(c.convert(url(data))[0],NATIVE)

    def test_native_crlf_and_comments(self):
        data=('# subscription vpn://do-not-copy\n'+NATIVE).replace('\n','\r\n').encode()
        self.assertEqual(c.convert(data)[0], NATIVE)

    def test_explicit_ipv4_conversion(self):
        native=NATIVE.replace('10.0.0.2/32','10.0.0.2/32, fd00::2/128').replace('DNS = 1.1.1.1','DNS = 1.1.1.1, 2606:4700:4700::1111').replace('0.0.0.0/0','0.0.0.0/0, ::/0')
        with self.assertRaises(c.ConversionError): c.convert(url(export(native)))
        result, removed=c.convert(url(export(native)),ipv4_only=True)
        self.assertEqual(result,NATIVE);self.assertEqual(removed,3)

    def test_ipv6_only_dns_removed(self):
        native=NATIVE.replace('DNS = 1.1.1.1','DNS = 2606:4700:4700::1111')
        result,removed=c.convert(native.encode(),ipv4_only=True)
        self.assertNotIn('DNS =', result);self.assertEqual(removed,1)

    def test_ipv6_only_address_or_routes_rejected(self):
        for native in [NATIVE.replace('10.0.0.2/32','fd00::2/128'), NATIVE.replace('0.0.0.0/0','::/0')]:
            with self.assertRaises(c.ConversionError): c.convert(native.encode(),ipv4_only=True)

    def test_all_awg_fields_preserved(self):
        extra='I2 = <rc 8><t>\nContentPaddingAddition = 10-100\nRekeyAfterTime = 100-120\nRekeyTimeout = 3-7\nRejectAfterTime = 150-180\nKeepaliveTimeout = 5-15\nMaxHandshakeAttempts = 15-20\n'
        native=NATIVE.replace('[Peer]',extra+'\n[Peer]')
        out,_=c.convert(url(export(native)))
        for line in extra.splitlines():self.assertIn(line,out)

    def test_incomplete_and_other_protocols(self):
        cases=[{'config_version':2,'api_key':'secret-not-output'}, {'containers':[{'container':'amnezia-awg','awg':{'port':51820}}]}, {'containers':[{'container':'amnezia-openvpn','openvpn':{'last_config':json.dumps({'config':NATIVE})}}]}, {'containers':[{'awg':{'last_config':json.dumps({'client_priv_key':KEY1})}}]}]
        for value in cases:
            with self.subTest(value=list(value)):
                with self.assertRaises(c.ConversionError):c.convert(url(value))

    def test_multiple_profiles_require_selection(self):
        obj=export();obj['containers']+=export(NATIVE.replace('10.0.0.2','10.0.0.3'))['containers']
        with self.assertRaises(c.ConversionError):c.convert(url(obj))
        self.assertIn('10.0.0.3/32',c.convert(url(obj),profile_index=2)[0])
        for n in [0,3]:
            with self.assertRaises(c.ConversionError):c.convert(url(obj),profile_index=n)

    def test_invalid_profile_does_not_expose_secrets(self):
        cases=[NATIVE+'PostUp = reboot\n',NATIVE+'\n[Peer]\nPublicKey = '+KEY1, NATIVE.replace('PrivateKey = '+KEY1,'PrivateKey = very-private-invalid-value'), NATIVE.replace('MTU = 1280','MTU = 1'),NATIVE.replace('192.0.2.1:51820','host;reboot:51820'),NATIVE.replace('Address = 10.0.0.2/32','Address = 10.0.0.2/32, 10.0.0.3/32'),NATIVE.replace('DNS = 1.1.1.1','DNS = dns.example.com'), NATIVE.replace('S4 = 12','S4 = 12\nS4 = 14')]
        for native in cases:
            with self.assertRaises(c.ConversionError) as raised:c.convert(url(export(native)))
            self.assertNotIn(KEY1,str(raised.exception));self.assertNotIn('very-private-invalid-value',str(raised.exception))

    def test_compression_limits_and_corruption(self):
        raw=json.dumps(export()).encode();good=qt(raw)
        for data in [good[:10],good+b'trailing',(len(raw)+1).to_bytes(4,'big')+good[4:],(c.MAX_JSON+1).to_bytes(4,'big')+good[4:], b'vpn://invalid!!!!', b'x'*(c.MAX_INPUT+1),b'']:
            with self.assertRaises(c.ConversionError):c.convert(data)
        bomb=(1).to_bytes(4,'big')+zlib.compress(b'x'*(c.MAX_JSON+2))
        with self.assertRaises(c.ConversionError):c.convert(bomb)

    def test_json_duplicate_nested_and_wrong_root(self):
        for data in [b'{"containers":[],"containers":[]}',b'['*1100+b']'*1100, qt(b'[]')]:
            with self.assertRaises(c.ConversionError):c.convert(data)

    def test_exclusive_private_file(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'router.conf'
            c.save_private(out,NATIVE)
            self.assertEqual(out.read_text(),NATIVE)
            with self.assertRaises(FileExistsError):c.save_private(out,'overwrite')
            self.assertEqual(out.read_text(),NATIVE)
            if os.name != 'nt':self.assertEqual(out.stat().st_mode & 0o777,0o600)

    def test_cli_file_roundtrip_and_failure_no_output(self):
        with tempfile.TemporaryDirectory() as temp:
            inp=Path(temp)/'in.vpn';out=Path(temp)/'router.conf';inp.write_bytes(url(export()))
            cmd=[sys.executable,str(ROOT/'tools/convert_profile.py'),'--input',str(inp),'--output',str(out),'--ipv4-only']
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(out.read_text(),NATIVE)
            self.assertEqual(inp.read_bytes(),url(export()))
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(out.read_text(),NATIVE)
            inp.write_bytes(url({'config_version':2,'secret':KEY1}));out.unlink()
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertFalse(out.exists())
            self.assertNotIn(KEY1,result.stdout+result.stderr)


if __name__=='__main__': unittest.main()
