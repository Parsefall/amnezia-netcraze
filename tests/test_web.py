import base64
import http.client
import importlib.util
import ipaddress
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('panel', ROOT/'web/server.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
PASSWORD = 'synthetic-panel-password'

class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tls = tempfile.TemporaryDirectory()
        folder = Path(cls.tls.name)
        openssl = shutil.which('openssl') or 'C:/Program Files/Git/usr/bin/openssl.exe'
        subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-keyout',str(folder/'key.pem'),'-out',str(folder/'cert.pem'),
                        '-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        cls.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.context.minimum_version = ssl.TLSVersion.TLSv1_2
        cls.context.load_cert_chain(folder/'cert.pem',folder/'key.pem')
        cls.client_context = ssl.create_default_context(cafile=str(folder/'cert.pem'))
        cls.password = w.password_record(PASSWORD)
    @classmethod
    def tearDownClass(cls): cls.tls.cleanup()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)/'opt/etc/awg3'
        (self.base/'conf').mkdir(parents=True)
        (self.base/'conf/router.conf').write_text('PrivateKey = NEVER_DISPLAY_THIS_SECRET')
        (self.base/'managed.tsv').write_text(str(self.base/'conf/router.conf')+'\t0\tOpkgTun0\n')
        self.calls = []
        self.fail_action = False
        self.app = w.Application({'bind':'192.168.1.1','network':'192.168.1.0/24','port':8088,'password':self.password},self.base,self.runner,Path(self.tmp.name)/'run')
        self.app.network = ipaddress.ip_network('127.0.0.0/8')
        self.server = w.Server(('127.0.0.1',0),self.app,ROOT/'web',self.context)
        self.app.authority = '127.0.0.1:'+str(self.server.server_port)
        self.app.origin = 'https://'+self.app.authority
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.cookie = self.csrf = ''
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()
    def runner(self,args,timeout=75):
        self.calls.append(args)
        if args[-1]=='latest-handshakes': return 0,'PUBLIC_KEY\t1700000000\n'
        if args[-1]=='transfer': return 0,'PUBLIC_KEY\t1234\t5678\n'
        if args[-1]=='show ping-check': return 0,'profile: AWG3Check\nstatus: pass'
        if len(args)>1 and args[1]=='import':
            self.import_bytes = Path(args[2]).read_bytes()
            self.import_path = Path(args[2])
        if self.fail_action: return 1,'ERROR: previous configuration restored\nPrivateKey = NEVER_DISPLAY_THIS_SECRET'
        return 0,'Profile replaced; verify handshake'
    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPSConnection('127.0.0.1',self.server.server_port,context=self.client_context,timeout=5)
        hdr={'Host':self.app.authority,'Origin':self.app.origin,'Content-Type':'application/json','Cookie':self.cookie,'X-CSRF-Token':self.csrf}
        if headers: hdr.update(headers)
        data=json.dumps(body).encode() if body is not None else None
        connection.request(method,path,data,headers=hdr)
        response=connection.getresponse(); raw=response.read(); result=(response.status,dict(response.getheaders()),raw)
        connection.close();return result
    def login(self):
        status,headers,raw=self.request('POST','/api/login',{'password':PASSWORD})
        self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';')[0];self.csrf=json.loads(raw)['csrf']
        return headers
    def test_tls_login_and_cookie(self):
        headers=self.login()
        self.assertIn('Secure',headers['Set-Cookie']);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        status,headers,body=self.request('GET','/api/status')
        self.assertEqual(status,200);self.assertNotIn(b'NEVER_DISPLAY',body);self.assertNotIn(b'PUBLIC_KEY',body)
        data=json.loads(body);self.assertFalse(data['running']);self.assertEqual(data['tunnels'][0]['received'],1234)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
    def test_unauthenticated_actions_and_state(self):
        self.assertEqual(self.request('GET','/api/status')[0],401)
        self.assertEqual(self.request('POST','/api/action',{'action':'up'})[0],401)
        self.assertEqual(self.calls,[])
    def test_host_origin_csrf_and_lan(self):
        self.login()
        for headers in [{'Host':'evil.test'},{'Origin':'https://evil.test'},{'X-CSRF-Token':'wrong'}]:
            self.assertEqual(self.request('POST','/api/action',{'action':'stop'},headers)[0],403)
        self.app.network=ipaddress.ip_network('192.168.1.0/24')
        self.assertEqual(self.request('GET','/api/status')[0],403)
        self.assertEqual(self.calls,[])
    def test_expiry_and_logout(self):
        self.login();self.request('POST','/api/logout',{})
        self.assertEqual(self.request('GET','/api/session')[0],401)
        self.login()
        for record in self.app.sessions.values():record['expires']=0
        self.assertEqual(self.request('GET','/api/session')[0],401)
    def test_rate_limit(self):
        for i in range(5):self.assertEqual(self.request('POST','/api/login',{'password':'wrong'})[0],401)
        self.assertEqual(self.request('POST','/api/login',{'password':PASSWORD})[0],429)
    def test_fixed_actions_no_shell(self):
        self.login()
        self.assertEqual(self.request('POST','/api/action',{'action':'up'})[0],200)
        self.assertEqual(self.calls[-1],[w.SERVICE,'up'])
        for action in ['up; reboot','save','__run','repair','import /etc/passwd']:
            self.assertEqual(self.request('POST','/api/action',{'action':action})[0],400)
        self.assertEqual(len(self.calls),1)
    def test_upload_temp_cleanup_and_validation(self):
        self.login();data=base64.b64encode(b'vpn://synthetic-test').decode()
        status,_,raw=self.request('POST','/api/action',{'action':'import','name':'router','data':data})
        self.assertEqual(status,200);self.assertEqual(self.import_bytes,b'vpn://synthetic-test');self.assertFalse(self.import_path.exists())
        self.assertNotIn(b'vpn://',raw)
        for name in ['../router','/etc/passwd','x;id','router.conf']:
            self.assertEqual(self.request('POST','/api/action',{'action':'import','name':name,'data':data})[0],400)
        self.assertEqual(self.request('POST','/api/action',{'action':'import','name':'router','data':'!!!'})[0],400)
    def test_per_tunnel_actions(self):
        self.login()
        for action in ('tunnel-up','tunnel-down','delete'):
            self.assertEqual(self.request('POST','/api/action',{'action':action,'name':'router'})[0],200)
            self.assertEqual(self.calls[-1],[w.SERVICE,action,'router'])
            for name in ['unknown','../router','router; reboot']:
                self.assertEqual(self.request('POST','/api/action',{'action':action,'name':name})[0],400)
        self.assertEqual(self.request('POST','/api/action',{'action':'rename','name':'router','label':'My VPN'})[0],200)
        self.assertEqual(self.calls[-1],[w.SERVICE,'rename','router','My VPN'])
    def test_create_uses_fixed_command(self):
        self.login()
        body={'action':'create','name':'second','data':base64.b64encode(b'synthetic').decode()}
        self.assertEqual(self.request('POST','/api/action',body)[0],200)
        self.assertEqual(self.calls[-1][0:2],[w.SERVICE,'create'])
        self.assertEqual(self.calls[-1][-1],'second')
        self.assertFalse(Path(self.calls[-1][2]).exists())
    def test_paused_and_unmapped_profiles(self):
        (self.base/'conf/second.conf').write_text('synthetic')
        (self.base/'paused').mkdir();(self.base/'paused/router').touch()
        self.app.runpath.mkdir();(self.app.runpath/'running').touch()
        self.login()
        data=json.loads(self.request('GET','/api/status')[2])
        byname={x['profile']:x for x in data['tunnels']}
        self.assertFalse(byname['router']['active'])
        self.assertEqual(byname['router']['connection'],'disconnected')
        self.assertIsNone(byname['second']['interface'])
        (self.base/'paused/router').unlink()
        (self.app.runpath/'stopped-0').touch()
        data=json.loads(self.request('GET','/api/status')[2])
        self.assertTrue(data['tunnels'][0]['stopped'])
        self.assertFalse(data['tunnels'][0]['active'])
        (self.base/'conf/router.conf').unlink()
        data=json.loads(self.request('GET','/api/status')[2])
        self.assertEqual([x['profile'] for x in data['tunnels']],['second'])
    def test_update_endpoints_require_auth_and_csrf(self):
        self.assertEqual(self.request('GET','/api/update/status')[0],401)
        self.assertEqual(self.request('POST','/api/action',{'action':'update-start','version':'v9.0.0'})[0],401)
        self.login()
        self.assertEqual(self.request('POST','/api/action',{'action':'update-check'},{'X-CSRF-Token':'bad'})[0],403)
        response=self.request('GET','/api/update/status')
        self.assertEqual(response[0],200);self.assertEqual(json.loads(response[2])['current'],w.APP_VERSION)
        self.assertEqual(response[1]['X-App-Version'],w.APP_VERSION)
    def test_update_lock_blocks_mutations(self):
        self.login();(self.app.runpath/'update.lock').mkdir(parents=True)
        for action in ['stop','rename','delete','import']:
            self.assertEqual(self.request('POST','/api/action',{'action':action})[0],409)
        self.assertEqual(self.request('POST','/api/password',{'current':PASSWORD,'password':'another-panel-password'})[0],409)
        self.assertEqual(self.calls,[])
    def test_update_check_and_selection(self):
        self.login();self.app.updater.check=lambda:{'latest':'v9.0.0','available':True}
        self.assertEqual(json.loads(self.request('POST','/api/action',{'action':'update-check'})[2])['latest'],'v9.0.0')
        self.assertEqual(self.request('POST','/api/action',{'action':'update-start','version':'v9.0.0; reboot'})[0],400)
    def test_failure_redaction(self):
        self.login();self.fail_action=True
        status,_,raw=self.request('POST','/api/action',{'action':'stop'})
        self.assertEqual(status,400);self.assertNotIn(b'NEVER_DISPLAY',raw);self.assertIn(b'restored',raw)
    def test_restore_only_listed_safe_backup(self):
        folder=self.base/'backups/imports';folder.mkdir(parents=True)
        (folder/'router.A1b2C3').write_text('synthetic old config')
        self.login()
        data=json.loads(self.request('GET','/api/status')[2]);self.assertEqual(data['backups'][0]['id'],'router.A1b2C3')
        self.assertEqual(self.request('POST','/api/action',{'action':'restore','backup':'router.A1b2C3'})[0],200)
        self.assertEqual(self.calls[-1],[w.SERVICE,'import',str(folder/'router.A1b2C3'),'router'])
        for identifier in ['../../passwd','router.bad','other.A1b2C3']:
            self.assertEqual(self.request('POST','/api/action',{'action':'restore','backup':identifier})[0],400)
    def test_busy_no_parallel_mutation(self):
        self.login();self.app.operation.acquire()
        try:self.assertEqual(self.request('POST','/api/action',{'action':'up'})[0],409)
        finally:self.app.operation.release()
        self.assertEqual(self.calls,[])
    def test_password_change_revokes_sessions(self):
        self.login()
        self.assertEqual(self.request('POST','/api/password',{'current':PASSWORD,'password':'short'})[0],400)
        self.assertEqual(self.request('POST','/api/password',{'current':PASSWORD,'password':'another-synthetic-password'})[0],200)
        self.assertEqual(self.request('GET','/api/session')[0],401)
        config=json.loads((self.base/'web/settings.json').read_text())
        self.assertNotIn('another-synthetic-password',json.dumps(config))
        self.assertTrue(w.password_matches('another-synthetic-password',config['password']))
    def test_asset_allowlist(self):
        self.assertEqual(self.request('GET','/')[0],200)
        self.login()
        for path in ['/server.py','/../settings.json','/api/action','/conf/router.conf','/key.pem']:
            self.assertEqual(self.request('GET',path)[0],404)
    def test_body_limits_and_types(self):
        self.assertEqual(self.request('POST','/api/login',{'password':'x'*5000})[0],413)
        self.assertEqual(self.request('POST','/api/login',[],{'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('POST','/api/login',[])[0],400)
        self.login()
        # Oversized uploads are rejected from headers, before receiving secrets.
        connection=http.client.HTTPSConnection('127.0.0.1',self.server.server_port,context=self.client_context,timeout=5)
        connection.putrequest('POST','/api/action',skip_host=True)
        for key,value in {'Host':self.app.authority,'Origin':self.app.origin,'Content-Type':'application/json','Content-Length':str(w.MAX_BODY+1),'Cookie':self.cookie,'X-CSRF-Token':self.csrf}.items():connection.putheader(key,value)
        connection.endheaders()
        response=connection.getresponse();self.assertEqual(response.status,413);response.read();connection.close()
    def test_network_configuration(self):
        for bind,network,port in [('0.0.0.0','0.0.0.0/0',8088),('8.8.8.8','8.8.8.0/24',8088),('192.168.1.1','192.168.2.0/24',8088),('192.168.1.1','192.168.1.0/24',80)]:
            with self.assertRaises(ValueError):w.validate_network(bind,network,port)
        self.assertEqual(str(w.validate_network('192.168.1.1','192.168.1.0/24',8088)),'192.168.1.0/24')

if __name__=='__main__':unittest.main()
