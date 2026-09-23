#!/usr/bin/env python3
"""Local HTTPS control panel. No shell commands, remote assets or key downloads."""
import argparse
import base64
from collections import deque
import getpass
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time

_update_spec = importlib.util.spec_from_file_location('awg3_updates', Path(__file__).with_name('updater.py'))
updates = importlib.util.module_from_spec(_update_spec)
_update_spec.loader.exec_module(updates)
APP_VERSION = Path(__file__).with_name('VERSION').read_text().strip()

BASE = Path('/opt/etc/awg3')
SERVICE = '/opt/etc/init.d/S99awg3'
WATCHDOG = '/opt/etc/init.d/S100awg3-watchdog'
AWG = '/opt/bin/awg'
NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z')
MAX_BODY = 6 * 1024 * 1024
RFC1918 = tuple(ipaddress.ip_network(x) for x in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))

class PanelError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def password_record(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise PanelError(400, 'Password must contain 12–128 characters.')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return {'salt': salt, 'digest': digest, 'iterations': 600000}


def password_matches(password, record):
    if not isinstance(password, str) or len(password) > 128:
        return False
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), record['iterations']).hex()
    return hmac.compare_digest(digest, record['digest'])


def private_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def validate_network(bind, network, port):
    address = ipaddress.IPv4Address(bind)
    subnet = ipaddress.IPv4Network(network, strict=True)
    if not any(address in n and subnet.subnet_of(n) for n in RFC1918):
        raise ValueError('Use a private IPv4 LAN address and subnet.')
    if address not in subnet or subnet.prefixlen < 16 or not 1024 <= port <= 65535:
        raise ValueError('Invalid LAN subnet or port (1024–65535 required).')
    return subnet


def command(args, timeout=75):
    # Separate process group permits bounded cleanup without leaving a service child.
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=(os.name == 'posix'))
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'posix': os.killpg(p.pid, signal.SIGTERM)
        else: p.terminate()
        try: p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == 'posix': os.killpg(p.pid, signal.SIGKILL)
            else: p.kill()
            p.communicate()
        raise PanelError(504, 'Operation timed out. Inspect service state before retrying.') from None
    return p.returncode, out[:65536].decode('utf-8', 'replace')


def clean_diagnostic(text):
    # Do not display arbitrary values from profiles or raw engine diagnostics.
    lines = []
    for line in text.splitlines()[-100:]:
        if re.search(r'key|vpn://|\b[ISH][1-5]\s*[:=]', line, re.I): continue
        line = re.sub(r'[A-Za-z0-9+/_=-]{40,}', '[redacted]', line)
        lines.append(line[:300])
    return '\n'.join(lines)


def ping_states(output):
    """Associate status only with its interface, never an ISP's pass result."""
    result, iface, block_indent = {}, None, None
    for line in output.splitlines():
        text = line.strip()
        indent = len(line)-len(line.lstrip())
        if text in ('pingcheck:', 'interface:'):
            iface, block_indent = None, None
        match = re.fullmatch(r'name: (OpkgTun(?:0|[1-9][0-9]?))', text)
        if match:
            iface, block_indent = match[1], indent
        elif iface and text.startswith('status:'):
            value = text.split(':',1)[1].strip()
            result[iface] = value if value in ('pass', 'fail') else 'unknown'
            iface = None
        elif iface and text and indent < block_indent and not re.match(r'(ignore-fail|successcount|failcount):', text):
            # CLI key alignment varies; only section boundaries invalidate above.
            if text.endswith(':'): iface = None
    return result


class Application:
    def __init__(self, settings, base=BASE, runner=command, runpath=Path("/var/run/awg3")):
        self.settings, self.base, self.runner = settings, Path(base), runner
        self.runpath = Path(runpath)
        self.updater = updates.Manager(self.base, self.runpath, Path(__file__).parent)
        self.network = validate_network(settings['bind'], settings['network'], settings['port'])
        self.authority = settings['bind'] + ':' + str(settings['port'])
        self.origin = 'https://' + self.authority
        self.sessions, self.failures = {}, deque()
        self.auth_lock, self.operation = threading.Lock(), threading.Lock()

    def login(self, password):
        with self.auth_lock:
            now = time.monotonic()
            while self.failures and self.failures[0] < now - 60: self.failures.popleft()
            if len(self.failures) >= 5:
                raise PanelError(429, 'Too many attempts. Wait one minute.')
            if not password_matches(password, self.settings['password']):
                self.failures.append(now)
                raise PanelError(401, 'Incorrect password.')
            self.sessions = {k:v for k,v in self.sessions.items() if v['expires'] > now}
            if len(self.sessions) >= 16: self.sessions.pop(next(iter(self.sessions)))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions[token] = {'csrf': csrf, 'expires': now + 3600}
            return token, csrf

    def session(self, cookie):
        parsed = SimpleCookie()
        try: parsed.load(cookie or '')
        except Exception: raise PanelError(401, 'Login required.') from None
        token = parsed.get('awg3_session')
        token = token.value if token else ''
        with self.auth_lock:
            record = self.sessions.get(token)
            if not record or record['expires'] <= time.monotonic():
                self.sessions.pop(token, None)
                raise PanelError(401, 'Login required.')
            return token, record['csrf']

    def profiles(self):
        result = []
        for path in sorted((self.base/'conf').glob('*.conf')):
            if path.is_symlink() or not NAME.fullmatch(path.stem): continue
            result.append(path.stem)
        return result[:100]

    def status(self):
        tunnels = []
        state = self.base/'managed.tsv'
        if state.exists():
            for line in state.read_text().splitlines()[:100]:
                fields = line.split('\t')
                if len(fields) != 3: continue
                path, idx, ndms = fields
                if not re.fullmatch(r'(0|[1-9][0-9]?)', idx) or ndms != 'OpkgTun'+idx: continue
                name = Path(path).stem
                if not NAME.fullmatch(name) or Path(path) != self.base/'conf'/(name+'.conf') or name not in self.profiles(): continue
                rc, hs = self.runner([AWG, 'show', 'opkgtun'+idx, 'latest-handshakes'], 5)
                received = sent = handshake = 0
                if not rc:
                    for row in hs.splitlines():
                        pieces = row.split()
                        if len(pieces) == 2 and pieces[1].isdigit(): handshake = max(handshake, int(pieces[1]))
                    rc2, traffic = self.runner([AWG, 'show', 'opkgtun'+idx, 'transfer'], 5)
                    if not rc2:
                        for row in traffic.splitlines():
                            pieces = row.split()
                            if len(pieces) == 3 and all(x.isdigit() for x in pieces[1:]):
                                received += int(pieces[1]); sent += int(pieces[2])
                tunnels.append({'profile': name, 'interface': ndms, 'engine': rc == 0,
                                'handshake': handshake, 'received': received, 'sent': sent})
        mapped = {tunnel['profile'] for tunnel in tunnels}
        for name in self.profiles():
            if name not in mapped:
                tunnels.append({'profile':name, 'interface':None, 'engine':False,
                                'handshake':0, 'received':0, 'sent':0})
        backups = []
        for path in sorted((self.base/'backups/imports').glob('*'), key=lambda p:p.stat().st_mtime, reverse=True)[:50]:
            name, _, suffix = path.name.rpartition('.')
            if NAME.fullmatch(name) and re.fullmatch(r'[A-Za-z0-9]{6}', suffix) and not path.is_symlink() and path.is_file():
                backups.append({'id': path.name, 'profile': name, 'time': int(path.stat().st_mtime)})
        rc, ping = self.runner(['ndmc', '-c', 'show ping-check'], 8)
        checks = ping_states(ping) if rc == 0 else {}
        started = (self.runpath/'running').exists()
        for tunnel in tunnels:
            check = checks.get(tunnel['interface'], 'unknown')
            tunnel['paused'] = (self.base/'paused'/tunnel['profile']).exists()
            tunnel['stopped'] = bool(tunnel['interface'] and (self.runpath/('stopped-'+tunnel['interface'][7:])).exists())
            tunnel['active'] = started and tunnel['engine'] and not tunnel['paused'] and not tunnel['stopped']
            tunnel['connection'] = ('disconnected' if not tunnel['active'] or check == 'fail'
                                    else 'connected' if check == 'pass' else 'unverified')
            label = self.base/'names'/tunnel['profile']
            text = label.read_text().strip() if label.is_file() and not label.is_symlink() else ''
            tunnel['name'] = text if re.fullmatch(r'[A-Za-z0-9_. -]{1,64}', text) else tunnel['profile']
        active = any(tunnel['active'] for tunnel in tunnels)
        return {'running': active, 'started': started, 'profiles': self.profiles(), 'tunnels': tunnels, 'backups': backups,
                'enabled': (self.base/'enabled').exists(),
                'watchdog': (self.base/'watchdog-enabled').exists(),
                'pingcheck': clean_diagnostic(ping) if rc == 0 else 'PingCheck unavailable',
                'busy': self.operation.locked(), 'update': self.updater.status()}

    def ndmc(self, text):
        rc, output = self.runner(['ndmc', '-c', text], 12)
        if rc or re.search(r'\b(?:error\[|error:|failed|invalid)', output, re.I):
            # Do not return firmware output: running-config can contain secrets.
            raise PanelError(400, 'Firmware command failed: ' + text.split()[0])
        return output

    def pingcheck_action(self, body):
        action = body['action']
        iface = body.get('interface', '')
        if action != 'pingcheck-save':
            if not isinstance(iface, str) or not re.fullmatch(r'OpkgTun(0|[1-9][0-9]?)', iface):
                raise PanelError(400, 'Select a managed VPN interface.')
            idx = iface[7:]
            managed = self.base/'managed.tsv'
            rows = managed.read_text().splitlines() if managed.exists() else []
            owned = False
            for row in rows:
                fields = row.split('\t')
                if len(fields) != 3: continue
                path, number, name = fields
                stem = Path(path).stem
                if (number == idx and name == iface and NAME.fullmatch(stem)
                        and Path(path) == self.base/'conf'/(stem+'.conf')
                        and stem in self.profiles()): owned = True
            if not owned: raise PanelError(400, 'Interface is not managed by this service.')
        values = {}
        if action == 'pingcheck-apply':
            try:
                host = ipaddress.IPv4Address(body.get('host', ''))
                if host.is_multicast or host.is_unspecified or host.is_loopback or host.is_link_local or host.is_reserved:
                    raise ValueError()
            except (ValueError, TypeError):
                raise PanelError(400, 'Enter a unicast IPv4 test address.') from None
            for name, low, high in [('update-interval', 5, 3600), ('timeout', 1, 30),
                                    ('max-fails', 1, 100), ('min-success', 1, 100)]:
                value = body.get(name)
                if type(value) is not int or not low <= value <= high:
                    raise PanelError(400, 'Invalid ' + name)
                values[name] = value
            if values['timeout'] >= values['update-interval']:
                raise PanelError(400, 'Timeout must be shorter than the interval.')
        self.runpath.mkdir(parents=True, exist_ok=True)
        lock = self.runpath/'service.lock'
        try: lock.mkdir()
        except FileExistsError: raise PanelError(409, 'VPN service is busy. Try again later.') from None
        try:
            (lock/'pid').write_text(str(os.getpid())+'\n')
            if action == 'pingcheck-save':
                self.ndmc('system configuration save')
                return {'message': 'Firmware configuration saved, including other pending router changes.'}
            config = self.ndmc('show running-config')
            # Only retain whitelisted PingCheck commands from this interface block.
            match = re.search(r'^interface '+re.escape(iface)+r'\s*\n((?:[ \t]+[^\n]*\n|[ \t]*\n)*)', config+'\n', re.M)
            if not match: raise PanelError(400, 'VPN interface not found in firmware configuration.')
            previous = None
            restart = None
            for line in match[1].splitlines():
                line = line.strip()
                if line.startswith('ping-check profile '):
                    previous = line.removeprefix('ping-check profile ')
                    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', previous):
                        raise PanelError(400, 'Existing profile name cannot be safely restored.')
                if line.startswith('ping-check restart'):
                    if not re.fullmatch(r'ping-check restart(?: [A-Za-z0-9_./-]{1,64})?', line):
                        raise PanelError(400, 'Existing restart setting cannot be safely restored.')
                    restart = line
            if action == 'pingcheck-disable':
                if previous: self.ndmc('interface '+iface+' no ping-check profile')
                return {'message': 'PingCheck detached. Save firmware configuration to retain this after reboot.'}
            profile = 'AWG3Web'+idx+'_'+secrets.token_hex(4)
            assigned = False
            created = False
            try:
                self.ndmc('ping-check profile '+profile)
                created = True
                for setting in ['host '+str(host), 'mode icmp'] + [k+' '+str(v) for k,v in values.items()]:
                    self.ndmc('ping-check profile '+profile+' '+setting)
                assigned = True  # A timeout/error may occur after firmware applied the command.
                self.ndmc('interface '+iface+' ping-check profile '+profile)
                self.ndmc('interface '+iface+' no ping-check restart')
            except (PanelError, OSError):
                try:
                    if assigned:
                        self.ndmc('interface '+iface+(' ping-check profile '+previous if previous else ' no ping-check profile'))
                        if previous:
                            self.ndmc('interface '+iface+' '+(restart or 'no ping-check restart'))
                    if created: self.ndmc('no ping-check profile '+profile)
                except (PanelError, OSError):
                    raise PanelError(500, 'PingCheck failed and rollback could not be confirmed. Inspect Netcraze configuration.') from None
                raise PanelError(400, 'PingCheck failed; previous assignment retained. Nothing saved to startup configuration.') from None
            # Remove only a previous panel-created profile with no other references.
            warning = ''
            if previous and re.fullmatch(r'AWG3Web[0-9]{1,2}_[0-9a-f]{8}', previous):
                references = re.findall(r'^\s+ping-check profile '+re.escape(previous)+r'\s*$', config, re.M)
                if len(references) == 1:
                    try: self.ndmc('no ping-check profile '+previous)
                    except (PanelError, OSError): warning = ' Previous unused profile could not be removed.'
            return {'message': 'PingCheck applied. Wait for checks, then save firmware configuration for reboot.'+warning}
        finally:
            (lock/'pid').unlink(missing_ok=True)
            lock.rmdir()

    def execute(self, body):
        if not self.operation.acquire(blocking=False): raise PanelError(409, 'Another operation is running.')
        try:
            action = body.get('action')
            if action == 'update-check': return self.updater.check()
            if action == 'update-start': return self.updater.start(body.get('version'))
            if (self.runpath/'update.lock').exists(): raise PanelError(409, 'update_busy')
            if action in ('pingcheck-apply', 'pingcheck-disable', 'pingcheck-save'):
                return self.pingcheck_action(body)
            if action in ('up','stop','enable','disable'):
                args = [SERVICE, action]
            elif action in ('tunnel-up', 'tunnel-down', 'delete'):
                name = body.get('name')
                if not isinstance(name, str) or name not in self.profiles():
                    raise PanelError(400, 'Unknown tunnel.')
                args = [SERVICE, action, name]
            elif action == 'rename':
                name, label = body.get('name'), body.get('label')
                if (not isinstance(name, str) or name not in self.profiles()
                        or not isinstance(label, str) or label != label.strip()
                        or not re.fullmatch(r'[A-Za-z0-9_. -]{1,64}', label)):
                    raise PanelError(400, 'Use 1–64 Latin letters, digits, spaces, dot, dash or underscore.')
                args = [SERVICE, 'rename', name, label]
            elif action in ('watchdog-enable','watchdog-disable'):
                args = [WATCHDOG, action.split('-')[1]]
            elif action == 'restore':
                identifier = body.get('backup', '')
                name, _, suffix = identifier.rpartition('.') if isinstance(identifier, str) else ('','','')
                if not NAME.fullmatch(name) or not re.fullmatch(r'[A-Za-z0-9]{6}', suffix):
                    raise PanelError(400, 'Invalid backup.')
                path = self.base/'backups/imports'/identifier
                if path.is_symlink() or not path.is_file() or name not in self.profiles():
                    raise PanelError(400, 'Backup or target profile not found.')
                args = [SERVICE, 'import', str(path), name]
            elif action in ('import', 'create'):
                name, encoded = body.get('name', ''), body.get('data', '')
                if not isinstance(name, str) or not NAME.fullmatch(name) or name.endswith('.conf') or not isinstance(encoded, str):
                    raise PanelError(400, 'Invalid profile name or file.')
                try: data = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError): raise PanelError(400, 'Invalid file encoding.') from None
                if not 0 < len(data) <= 4*1024*1024: raise PanelError(400, 'File must be between 1 byte and 4 MiB.')
                # Service performs conversion, validation, stable mapping and rollback.
                with tempfile.TemporaryDirectory(prefix='web-import-', dir=self.base) as folder:
                    path = Path(folder)/'input.vpn'
                    with path.open('xb') as out: out.write(data)
                    os.chmod(path, 0o600)
                    return self.run_action([SERVICE, action, str(path), name])
            else: raise PanelError(400, 'Unknown action.')
            return self.run_action(args)
        except updates.UpdateError as error:
            raise PanelError(400, str(error)) from None
        finally:
            self.operation.release()

    def run_action(self, args):
        rc, output = self.runner(args)
        if rc:
            # Only messages from our wrapper; no raw profile/engine output.
            raise PanelError(400, 'Operation failed. ' + clean_diagnostic(output)[-1200:])
        return {'message': clean_diagnostic(output)[-1200:] or 'Done. Verify tunnel connectivity.'}

    def change_password(self, body):
        if (self.runpath/'update.lock').exists(): raise PanelError(409, 'update_busy')
        with self.auth_lock:
            if not password_matches(body.get('current'), self.settings['password']):
                raise PanelError(401, 'Incorrect current password.')
            record = password_record(body.get('password'))
            settings = dict(self.settings, password=record)
            private_json(self.base/'web/settings.json', settings)
            self.settings = settings
            self.sessions.clear()
        return {'message': 'Password changed. Sign in again.'}

class Handler(BaseHTTPRequestHandler):
    server_version = 'AmneziaNetcraze'
    def log_message(self, *args): pass  # Never log request bodies, cookies or keys.

    @property
    def app(self): return self.server.app

    def reply(self, code, data, content_type='application/json; charset=utf-8', cookie=None):
        if isinstance(data, dict): data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-App-Version', APP_VERSION)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Connection', 'close')
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def guard(self, mutation=False):
        try: allowed = ipaddress.ip_address(self.client_address[0]) in self.app.network
        except ValueError: allowed = False
        if not allowed: raise PanelError(403, 'Home LAN access only.')
        if self.headers.get_all('Host') != [self.app.authority]:
            raise PanelError(403, 'Use the configured router IP and port.')
        if mutation and self.headers.get_all('Origin') != [self.app.origin]:
            raise PanelError(403, 'Same-origin request required.')

    def do_GET(self):
        try:
            self.guard()
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if self.path in assets:
                file, mime = assets[self.path]
                return self.reply(200, (self.server.assets/file).read_bytes(), mime)
            _, csrf = self.app.session(self.headers.get('Cookie'))
            if self.path == '/api/session': return self.reply(200, {'csrf': csrf})
            if self.path == '/api/update/status': return self.reply(200, self.app.updater.status())
            if self.path == '/api/status': return self.reply(200, self.app.status())
            if self.path == '/api/log':
                path = self.app.base.parent.parent/'var/log/awg3.log'
                text = ''
                if path.is_file():
                    with path.open('rb') as f:
                        f.seek(max(0, path.stat().st_size - 16000))
                        text = f.read(16000).decode('utf-8', 'replace')
                return self.reply(200, {'log': clean_diagnostic(text)})
            raise PanelError(404, 'Not found.')
        except PanelError as e: self.reply(e.code, {'error': e.message})
        except (OSError, ValueError, updates.UpdateError): self.reply(503, {'error': 'Unable to read router state.'})

    def do_POST(self):
        try:
            self.guard(mutation=True)
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                raise PanelError(400, 'Content-Length required; chunked uploads are not supported.')
            try: size = int(self.headers.get('Content-Length'))
            except (TypeError, ValueError): raise PanelError(400, 'Invalid request size.') from None
            limit = 4096 if self.path in ('/api/login','/api/password') else MAX_BODY
            if not 0 < size <= limit: raise PanelError(413, 'Request too large or empty.')
            if self.headers.get_content_type() != 'application/json': raise PanelError(415, 'JSON required.')
            token = csrf = None
            if self.path != '/api/login':
                token, csrf = self.app.session(self.headers.get('Cookie'))
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), csrf):
                    raise PanelError(403, 'Invalid CSRF token.')
            raw = self.rfile.read(size)
            if len(raw) != size: raise PanelError(400, 'Incomplete request.')
            try: body = json.loads(raw)
            except (ValueError, RecursionError): raise PanelError(400, 'Invalid JSON.') from None
            if not isinstance(body, dict): raise PanelError(400, 'JSON object required.')
            if self.path == '/api/login':
                token, csrf = self.app.login(body.get('password'))
                return self.reply(200, {'csrf': csrf}, cookie='awg3_session='+token+'; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=3600')
            if self.path == '/api/logout':
                with self.app.auth_lock: self.app.sessions.pop(token, None)
                return self.reply(200, {'message':'Signed out.'}, cookie='awg3_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0')
            if self.path == '/api/action': return self.reply(200, self.app.execute(body))
            if self.path == '/api/password': return self.reply(200, self.app.change_password(body))
            raise PanelError(404, 'Not found.')
        except PanelError as e: self.reply(e.code, {'error': e.message})
        except (OSError, ValueError, TypeError): self.reply(503, {'error':'Operation unavailable. Inspect router state.'})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, app, assets, context=None):
        self.app, self.assets, self.context = app, Path(assets), context
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)
    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(10)
        if self.context: sock = self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()
    def handle_error(self, request, client_address): pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--bind', default='192.168.1.1')
    parser.add_argument('--network', default='192.168.1.0/24')
    parser.add_argument('--port', type=int, default=8088)
    args = parser.parse_args()
    os.umask(0o077)
    config = BASE/'web/settings.json'
    if args.setup:
        validate_network(args.bind, args.network, args.port)
        if not os.isatty(0): raise ValueError('Setup requires an interactive SSH terminal.')
        first = getpass.getpass('Panel password (12+ characters): ')
        second = getpass.getpass('Repeat password: ')
        if first != second: raise ValueError('Passwords differ.')
        record = password_record(first)
        folder = config.parent
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Generate the certificate before replacing a working configuration.
        rc, _ = command(['/opt/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-sha256', '-nodes',
                         '-days', '825', '-keyout', str(folder/'key.new.pem'), '-out', str(folder/'cert.new.pem'),
                         '-subj', '/CN=Amnezia-Netcraze', '-addext', 'subjectAltName=IP:'+args.bind], 90)
        if rc: raise ValueError('Certificate generation failed; install Entware openssl-util.')
        os.replace(folder/'key.new.pem', folder/'key.pem')
        os.replace(folder/'cert.new.pem', folder/'cert.pem')
        private_json(config, {'bind':args.bind,'network':args.network,'port':args.port,'password':record})
        print('Configured https://'+args.bind+':'+str(args.port))
        print('Self-signed certificate: compare the SHA256 fingerprint before trusting it:')
        rc, fingerprint = command(['/opt/bin/openssl','x509','-in',str(folder/'cert.pem'),'-noout','-fingerprint','-sha256'])
        print(fingerprint.strip())
        return
    settings = json.loads(config.read_text())
    app = Application(settings)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config.parent/'cert.pem', config.parent/'key.pem')
    with Server((settings['bind'], settings['port']), app, Path(__file__).parent, context) as server:
        server.serve_forever(poll_interval=0.5)

if __name__ == '__main__':
    try: main()
    except (PanelError, ValueError, OSError) as exc:
        print('Panel setup/start failed:', exc.message if isinstance(exc, PanelError) else str(exc))
        raise SystemExit(1)
