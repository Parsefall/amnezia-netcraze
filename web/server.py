#!/usr/bin/env python3
"""Local HTTP/HTTPS control panel. No shell commands, remote assets or key downloads."""
import argparse
import base64
from contextlib import contextmanager
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
    # A router with imported IP lists can have a large running-config. Never
    # silently truncate it: failover must see every route before changing any.
    if len(out) > 2 * 1024 * 1024:
        raise PanelError(503, 'Firmware response is too large.')
    return p.returncode, out.decode('utf-8', 'replace')


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


class FailoverRule:
    """Only validated, interface-directed firmware routing commands are replayed."""
    def __init__(self, command):
        words = command.split()
        self.kind = 'route'
        if words[:2] == ['ip', 'route']:
            start = 2
        elif len(words) > 4 and words[:2] == ['ip', 'policy'] and NAME.fullmatch(words[2]) and words[3] == 'route':
            start = 4
        elif len(words) > 5 and words[:2] == ['ip', 'policy'] and NAME.fullmatch(words[2]) and words[3:5] == ['permit', 'global']:
            self.kind, start = 'policy', 5
        elif words[:3] == ['dns-proxy', 'route', 'object-group'] and len(words) > 4 and NAME.fullmatch(words[3]):
            self.kind, start = 'dns', 4
        else:
            raise ValueError('Unsupported routing command')
        prefix = words[:start]
        if self.kind == 'route':
            destination = words[start]
            start += 1
            if destination == 'default':
                self.network = ipaddress.IPv4Network('0.0.0.0/0')
            else:
                if '/' not in destination and start < len(words) and not words[start].startswith('OpkgTun'):
                    destination += '/' + words[start].lstrip('/')
                    start += 1
                self.network = ipaddress.IPv4Network(destination, strict=True)
            if self.network.prefixlen == 0:
                prefix += ['default']
            elif self.network.prefixlen == 32:
                prefix += [str(self.network.network_address)]
            else:
                prefix += [str(self.network.network_address), str(self.network.netmask)]
        self.iface = words[start]
        iface_pattern = r'[A-Za-z][A-Za-z0-9_./-]{0,95}' if self.kind == 'policy' else r'OpkgTun(?:0|[1-9][0-9]?)'
        if not re.fullmatch(iface_pattern, self.iface):
            raise ValueError('A direct managed interface is required')
        tail = words[start+1:]
        if self.kind == 'policy':
            if tail and (len(tail) != 2 or tail[0] != 'order' or not tail[1].isdigit() or not 0 <= int(tail[1]) <= 65534):
                raise ValueError('Invalid policy order')
            suffix = tail
            self.remove = ' '.join(prefix[:3] + ['no', 'permit', 'global', self.iface])
        else:
            if not re.fullmatch(r'(?:auto ?)?(?:[0-9]+ ?)?(?:reject)?', ' '.join(tail)):
                raise ValueError('Unsupported route options')
            metric = next((x for x in tail if x.isdigit()), None)
            if metric and (self.kind == 'dns' or int(metric) > 65535):
                raise ValueError('Invalid metric')
            if 'reject' in tail and ('auto' not in tail or (self.kind == 'route' and self.network.prefixlen == 0)):
                raise ValueError('Invalid exclusive route')
            suffix = (['auto'] if 'auto' in tail else []) + ([metric] if metric else []) + (['reject'] if 'reject' in tail else [])
            self.remove = 'no ' + ' '.join(prefix + [self.iface] + ([metric] if metric else []))
        self.prefix, self.suffix = prefix, suffix
        self.command = ' '.join(prefix + [self.iface] + suffix)
        self.key = ' '.join(prefix + [self.iface])

    def through(self, iface):
        return FailoverRule(' '.join(self.prefix + [iface] + self.suffix))


def routing_rules(config):
    rules, unsupported, context = {}, set(), ''
    parent_interfaces, parent_indent = set(), -1
    for raw in config.splitlines():
        line = raw.strip()
        if not line or line == '!':
            context = ''
            parent_interfaces = set()
            continue
        indent = len(raw)-len(raw.lstrip())
        if parent_interfaces and indent > parent_indent:
            unsupported.update(parent_interfaces)
            continue
        parent_interfaces = set()
        if not raw[0].isspace():
            context = line if line == 'dns-proxy' or re.fullmatch(r'ip policy [A-Za-z0-9_.-]+', line) else ''
            command = line
        else:
            command = context + ' ' + line if context else ''
        if not (command.startswith(('ip route ', 'dns-proxy route ')) or re.match(r'ip policy \S+ (route |permit global )', command)):
            continue
        interfaces = set(re.findall(r'\bOpkgTun[0-9]+\b', command))
        parent_interfaces, parent_indent = interfaces, indent
        if not interfaces and not re.match(r'ip policy \S+ permit global ', command):
            continue
        try:
            rule = FailoverRule(command)
            if rule.key in rules and rules[rule.key].command != rule.command:
                raise ValueError('Ambiguous route')
            rules[rule.key] = rule
        except (ValueError, IndexError):
            unsupported.update(interfaces)
    return rules, unsupported


class Failover:
    """Background firmware routing transactions; never reloads VPN credentials."""
    def __init__(self, app, clock=time.monotonic):
        self.app, self.clock = app, clock
        self.path = app.base/'failover.json'
        self.journal = app.base/'failover-journal.json'
        self.recovered = {}
        self.error = ''
        self.stop = threading.Event()

    def read(self, path):
        try:
            if path.is_symlink() or path.stat().st_size > 2*1024*1024:
                raise PanelError(503, 'failover_invalid_state')
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value, dict): raise ValueError()
            return value
        except FileNotFoundError:
            return {}
        except (ValueError, TypeError):
            raise PanelError(503, 'failover_invalid_state') from None

    def pairs(self):
        pairs = self.read(self.path)
        if len(pairs) > 100 or any(not isinstance(k, str) or not NAME.fullmatch(k) or not isinstance(v, str) or not NAME.fullmatch(v) for k,v in pairs.items()):
            raise PanelError(503, 'failover_invalid_state')
        for source in pairs:
            seen, node = set(), source
            while node in pairs:
                if node in seen: raise PanelError(400, 'failover_cycle')
                seen.add(node)
                node = pairs[node]
        return pairs

    def record(self):
        record = self.read(self.journal)
        if not record: return {}
        try:
            if record['phase'] not in ('pending', 'active'): raise ValueError()
            for field in ('before', 'after'):
                if not isinstance(record[field], list) or len(record[field]) > 10000: raise ValueError()
                for line in record[field]:
                    if not isinstance(line, str) or FailoverRule(line).command != line: raise ValueError()
            if not isinstance(record['via'], dict) or any(not NAME.fullmatch(k) or not isinstance(v, str) or not NAME.fullmatch(v) for k,v in record['via'].items()): raise ValueError()
        except (KeyError, ValueError, TypeError, IndexError):
            raise PanelError(503, 'failover_invalid_state') from None
        return record

    @contextmanager
    def lock(self):
        self.app.runpath.mkdir(parents=True, exist_ok=True)
        lock = self.app.runpath/'service.lock'
        try: lock.mkdir()
        except FileExistsError: raise PanelError(409, 'VPN service is busy. Try again later.') from None
        try:
            (lock/'pid').write_text(str(os.getpid())+'\n')
            if (self.app.runpath/'update.lock').exists(): raise PanelError(409, 'update_busy')
            yield
        finally:
            (lock/'pid').unlink(missing_ok=True)
            lock.rmdir()

    def snapshot(self):
        return routing_rules(self.app.ndmc('show running-config'))

    def restore(self, record):
        """Also handles a crash/timeout between any two firmware commands."""
        before = {FailoverRule(x).key:FailoverRule(x) for x in record['before']}
        after = {FailoverRule(x).key:FailoverRule(x) for x in record['after']}
        current, _ = self.snapshot()
        for key in before.keys() | after.keys():
            present = current.get(key)
            allowed = {x.command for x in (before.get(key), after.get(key)) if x}
            if present and present.command not in allowed and not (record['phase'] == 'pending' and present.kind == 'policy'):
                raise PanelError(409, 'failover_route_conflict')
        # Returning to the primary is itself a recoverable transaction.
        record = dict(record, phase='pending')
        private_json(self.journal, record)
        for rule in sorted(before.values(), key=self.apply_order):
            key = rule.key
            if rule.kind == 'policy' or key not in current or current[key].command != rule.command:
                self.app.ndmc(rule.command)
        # Firmware may either upsert a DNS group or keep one entry per interface.
        # Inspect after adding originals, and delete only the temporary destination.
        current, _ = self.snapshot()
        for key, rule in after.items():
            if key not in before and key in current:
                self.app.ndmc(rule.remove)
        verified, _ = self.snapshot()
        if any(verified.get(k) is None or verified[k].command != r.command for k,r in before.items()) or any(k in verified for k in after.keys()-before.keys()):
            raise PanelError(503, 'failover_restore_failed')
        self.journal.unlink(missing_ok=True)

    @staticmethod
    def apply_order(rule):
        return (rule.kind == 'policy', tuple(rule.prefix), int(rule.suffix[-1]) if rule.kind == 'policy' and rule.suffix else -1, rule.iface)

    def reset(self):
        with self.lock():
            record = self.record()
            if record: self.restore(record)
        self.recovered.clear()

    def configure(self, source, target):
        tunnels = {t['profile']:t for t in self.app.status()['tunnels']}
        if not isinstance(source, str) or source not in tunnels or not tunnels[source]['interface']:
            raise PanelError(400, 'Unknown tunnel.')
        if target is not None and (not isinstance(target, str) or target not in tunnels or not tunnels[target]['interface']):
            raise PanelError(400, 'failover_unknown_backup')
        if source == target: raise PanelError(400, 'failover_cycle')
        pairs = self.pairs()
        if target is None: pairs.pop(source, None)
        else: pairs[source] = target
        for node in pairs:
            seen = set()
            while node in pairs:
                if node in seen: raise PanelError(400, 'failover_cycle')
                seen.add(node); node = pairs[node]
        with self.lock():
            record = self.record()
            if target:
                config = self.app.ndmc('show running-config')
                for name in (source, target):
                    iface = tunnels[name]['interface']
                    if not re.search(r'^interface '+re.escape(iface)+r'\s*\n(?:[ \t]+[^\n]*\n)*?[ \t]+ping-check profile \S+', config+'\n', re.M):
                        raise PanelError(400, 'failover_ping_required')
                rules, unsupported = routing_rules(config)
                if record:
                    for line in record['after']: rules.pop(FailoverRule(line).key, None)
                    for line in record['before']:
                        rule = FailoverRule(line); rules[rule.key] = rule
                if tunnels[source]['interface'] in unsupported:
                    raise PanelError(400, 'failover_unsupported_route')
                if not any(r.iface == tunnels[source]['interface'] for r in rules.values()):
                    raise PanelError(400, 'failover_no_routes')
            if record: self.restore(record)
            private_json(self.path, pairs)
        self.recovered.clear()
        self.error = ''
        return {'message':'failover_saved'}

    def desired_targets(self, pairs, tunnels, previous):
        via = {}
        now = self.clock()
        def enabled(t):
            return t and not t['paused'] and not t['stopped'] and t.get('started', False)
        def healthy(t):
            return enabled(t) and t['engine'] and t['ping'] == 'pass'
        for source in pairs:
            primary = tunnels.get(source)
            if not enabled(primary):
                self.recovered.pop(source, None)
                continue
            old = previous.get(source)
            if healthy(primary):
                since = self.recovered.setdefault(source, now)
                if old and healthy(tunnels.get(old)) and now-since < 30:
                    via[source] = old
                continue
            self.recovered.pop(source, None)
            if primary['ping'] != 'fail':
                if old and healthy(tunnels.get(old)): via[source] = old
                continue
            node, seen = source, set()
            while node in pairs and node not in seen:
                seen.add(node); node = pairs[node]
                candidate = tunnels.get(node)
                if healthy(candidate):
                    via[source] = node
                    break
                if not enabled(candidate) or candidate['ping'] != 'fail': break
        return via

    def tick(self):
        if not self.app.operation.acquire(blocking=False): return
        try:
            if (self.app.runpath/'update.lock').exists(): return
            pairs, record = self.pairs(), self.record()
            if not pairs and not record: return
            with self.lock():
                if record and record['phase'] == 'pending':
                    self.restore(record); record = {}
                status = self.app.status()
                tunnels = {t['profile']:dict(t, started=status['started']) for t in status['tunnels']}
                current, unsupported = self.snapshot()
                if record:
                    before_rules = {FailoverRule(x).key: x for x in record['before']}
                    added_keys = {FailoverRule(x).key for x in record['after']} - before_rules.keys()
                    # After a router reboot, startup-config may already be original.
                    if all(k in current and current[k].command == v for k,v in before_rules.items()) and not added_keys & current.keys():
                        self.journal.unlink(missing_ok=True)
                        record = {}
                via = self.desired_targets(pairs, tunnels, record.get('via', {}))
                # Reconstruct the user's routing configuration from the durable journal.
                logical = dict(current)
                if record:
                    for line in record['after']:
                        rule = FailoverRule(line)
                        if rule.key not in current or current[rule.key].command != line:
                            raise PanelError(409, 'failover_route_conflict')
                        logical.pop(rule.key)
                    for line in record['before']:
                        rule = FailoverRule(line)
                        if rule.key in logical: raise PanelError(409, 'failover_route_conflict')
                        logical[rule.key] = rule
                mapping = {tunnels[a]['interface']:tunnels[b]['interface'] for a,b in via.items()}
                if unsupported & mapping.keys(): raise PanelError(400, 'failover_unsupported_route')
                desired = {}
                allowed = {}
                for rule in logical.values():
                    replacement = rule.through(mapping[rule.iface]) if rule.iface in mapping else rule
                    if rule.iface in mapping:
                        if rule.kind == 'policy' and not rule.suffix:
                            raise PanelError(400, 'failover_unsupported_route')
                        target = replacement.iface
                        if target not in allowed:
                            rc, output = self.app.runner([AWG, 'show', target.lower(), 'allowed-ips'], 5)
                            allowed[target] = []
                            if rc: raise PanelError(503, 'failover_backup_coverage')
                            for word in output.replace(',', ' ').split():
                                try: allowed[target].append(ipaddress.IPv4Network(word))
                                except ValueError: pass
                        network = rule.network if rule.kind == 'route' else ipaddress.IPv4Network('0.0.0.0/0')
                        if not any(network.subnet_of(n) for n in allowed[target]):
                            raise PanelError(400, 'failover_backup_coverage')
                    if replacement.key in desired and desired[replacement.key].command != replacement.command:
                        previous = desired[replacement.key]
                        if previous.kind == replacement.kind == 'policy' and previous.suffix and replacement.suffix:
                            replacement = min((previous, replacement), key=lambda r:int(r.suffix[-1]))
                        else:
                            raise PanelError(409, 'failover_route_conflict')
                    desired[replacement.key] = replacement
                # Removing a policy member renumbers the following members in
                # firmware. Include these order changes in the recovery journal.
                policy_groups = {tuple(r.prefix) for r in desired.values() if r.kind == 'policy' and any(x.kind == 'policy' and x.prefix == r.prefix and x.iface in mapping for x in logical.values())}
                for prefix in policy_groups:
                    members = [r for r in desired.values() if tuple(r.prefix) == prefix]
                    if any(not r.suffix for r in members): raise PanelError(400, 'failover_unsupported_route')
                    for order, member in enumerate(sorted(members, key=lambda r:int(r.suffix[-1]))):
                        desired[member.key] = FailoverRule(' '.join(member.prefix + [member.iface, 'order', str(order)]))
                before = sorted(r.command for k,r in logical.items() if tuple(r.prefix) in policy_groups or k not in desired or desired[k].command != r.command)
                after = sorted(r.command for k,r in desired.items() if tuple(r.prefix) in policy_groups or k not in logical or logical[k].command != r.command)
                if record and record['before'] == before and record['after'] == after and record['via'] == via:
                    self.error = ''
                    return
                if record: self.restore(record)
                if not before and not after:
                    self.error = 'failover_no_routes' if via else ''
                    return
                # Both endpoints of every change are saved BEFORE the first mutation.
                record = {'phase':'pending', 'before':before, 'after':after, 'via':via}
                private_json(self.journal, record)
                try:
                    after_keys = {FailoverRule(x).key for x in after}
                    # Remove replaced policy members first, then assign final
                    # ranks in order; firmware renumbers members on each write.
                    for line in before:
                        rule = FailoverRule(line)
                        if rule.kind == 'policy' and rule.key not in after_keys:
                            self.app.ndmc(rule.remove)
                    for rule in sorted((FailoverRule(x) for x in after), key=self.apply_order):
                        self.app.ndmc(rule.command)
                    intermediate, _ = self.snapshot()
                    for line in before:
                        rule = FailoverRule(line)
                        if rule.key not in after_keys and rule.key in intermediate: self.app.ndmc(rule.remove)
                    actual, _ = self.snapshot()
                    if any(actual.get(k) is None or actual[k].command != r.command for k,r in desired.items()) or any(FailoverRule(x).key in actual for x in before if FailoverRule(x).key not in desired):
                        raise PanelError(503, 'failover_apply_failed')
                    record['phase'] = 'active'
                    private_json(self.journal, record)
                except (PanelError, OSError):
                    try: self.restore(record)
                    except (PanelError, OSError): raise PanelError(503, 'failover_restore_failed') from None
                    raise
                self.error = ''
        except PanelError as error:
            if error.code != 409 or error.message == 'failover_route_conflict': self.error = error.message
        except (OSError, ValueError):
            self.error = 'failover_invalid_state'
        finally:
            self.app.operation.release()

    def run(self):
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(10)


class Application:
    def __init__(self, settings, base=BASE, runner=command, runpath=Path("/var/run/awg3")):
        self.settings, self.base, self.runner = settings, Path(base), runner
        self.runpath = Path(runpath)
        self.updater = updates.Manager(self.base, self.runpath, Path(__file__).parent)
        self.network = validate_network(settings['bind'], settings['network'], settings['port'])
        self.authority = settings['bind'] + ':' + str(settings['port'])
        self.origin = 'https://' + self.authority
        self.slots = threading.BoundedSemaphore(8)
        self.sessions, self.failures = {}, deque()
        self.auth_lock, self.operation = threading.Lock(), threading.Lock()
        self.failover = Failover(self)

    def login(self, password, transport='https'):
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
            self.sessions[token] = {'csrf': csrf, 'expires': now + 3600, 'transport': transport}
            return token, csrf

    def session(self, cookie, transport='https'):
        parsed = SimpleCookie()
        try: parsed.load(cookie or '')
        except Exception: raise PanelError(401, 'Login required.') from None
        token = parsed.get('awg3_session' if transport == 'https' else 'awg3_http_session')
        token = token.value if token else ''
        with self.auth_lock:
            record = self.sessions.get(token)
            if not record or record['expires'] <= time.monotonic():
                self.sessions.pop(token, None)
                raise PanelError(401, 'Login required.')
            if record.get('transport', 'https') != transport:
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
            tunnel['ping'] = check
            tunnel['paused'] = (self.base/'paused'/tunnel['profile']).exists()
            tunnel['stopped'] = bool(tunnel['interface'] and (self.runpath/('stopped-'+tunnel['interface'][7:])).exists())
            tunnel['active'] = started and tunnel['engine'] and not tunnel['paused'] and not tunnel['stopped']
            tunnel['connection'] = ('disconnected' if not tunnel['active'] or check == 'fail'
                                    else 'connected' if check == 'pass' else 'unverified')
            label = self.base/'names'/tunnel['profile']
            text = label.read_text().strip() if label.is_file() and not label.is_symlink() else ''
            tunnel['name'] = text if re.fullmatch(r'[A-Za-z0-9_. -]{1,64}', text) else tunnel['profile']
        try:
            pairs, failover_state = self.failover.pairs(), self.failover.record()
            failover_error = self.failover.error
        except PanelError as error:
            pairs, failover_state, failover_error = {}, {}, error.message
        for tunnel in tunnels:
            tunnel['backup'] = pairs.get(tunnel['profile'])
            tunnel['via'] = failover_state.get('via', {}).get(tunnel['profile']) if failover_state.get('phase') == 'active' else None
        active = any(tunnel['active'] for tunnel in tunnels)
        return {'running': active, 'started': started, 'profiles': self.profiles(), 'tunnels': tunnels, 'backups': backups,
                'enabled': (self.base/'enabled').exists(),
                'watchdog': (self.base/'watchdog-enabled').exists(),
                'pingcheck': clean_diagnostic(ping) if rc == 0 else 'PingCheck unavailable',
                'busy': self.operation.locked(), 'update': self.updater.status(), 'failover_error':failover_error}

    def ndmc(self, text):
        rc, output = self.runner(['ndmc', '-c', text], 12)
        if rc or re.search(r'\b(?:error\[|error:|failed|invalid)', output, re.I):
            # Do not return firmware output: running-config can contain secrets.
            raise PanelError(400, 'Firmware command failed: ' + text.split()[0])
        return output

    def pingcheck_action(self, body):
        action = body['action']
        iface = body.get('interface', '')
        if action == 'pingcheck-save' and self.failover.record():
            raise PanelError(409, 'failover_save_blocked')
        if action == 'pingcheck-disable':
            pairs = self.failover.pairs()
            used = set(pairs) | set(pairs.values())
            if used and any(t['interface'] == iface and t['profile'] in used for t in self.status()['tunnels']):
                raise PanelError(409, 'failover_ping_in_use')
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
            if action == 'update-start':
                if self.failover.record(): self.failover.reset()
                return self.updater.start(body.get('version'))
            if (self.runpath/'update.lock').exists(): raise PanelError(409, 'update_busy')
            if action == 'failover-set':
                return self.failover.configure(body.get('name'), body.get('backup'))
            if action == 'delete':
                pairs = self.failover.pairs()
                name = body.get('name')
                if isinstance(name, str) and (name in pairs or name in pairs.values()):
                    raise PanelError(409, 'failover_tunnel_in_use')
            if action in ('stop', 'tunnel-down', 'delete') and self.failover.record():
                self.failover.reset()
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

    @property
    def transport(self): return 'https' if isinstance(self.connection, ssl.SSLSocket) else 'http'

    def session_cookie(self, token, age):
        name = 'awg3_session' if self.transport == 'https' else 'awg3_http_session'
        secure = '; Secure' if self.transport == 'https' else ''
        return name+'='+token+'; Path=/; HttpOnly'+secure+'; SameSite=Strict; Max-Age='+str(age)

    def guard(self, mutation=False):
        try: allowed = ipaddress.ip_address(self.client_address[0]) in self.app.network
        except ValueError: allowed = False
        if not allowed: raise PanelError(403, 'Home LAN access only.')
        authority = self.app.authority if self.transport == 'https' else self.server.server_address[0]+':'+str(self.server.server_port)
        origin = self.app.origin if self.transport == 'https' else 'http://'+authority
        if self.headers.get_all('Host') != [authority]:
            raise PanelError(403, 'Use the configured router IP and port.')
        if mutation and self.headers.get_all('Origin') != [origin]:
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
            _, csrf = self.app.session(self.headers.get('Cookie'), self.transport)
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
                token, csrf = self.app.session(self.headers.get('Cookie'), self.transport)
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), csrf):
                    raise PanelError(403, 'Invalid CSRF token.')
            raw = self.rfile.read(size)
            if len(raw) != size: raise PanelError(400, 'Incomplete request.')
            try: body = json.loads(raw)
            except (ValueError, RecursionError): raise PanelError(400, 'Invalid JSON.') from None
            if not isinstance(body, dict): raise PanelError(400, 'JSON object required.')
            if self.path == '/api/login':
                token, csrf = self.app.login(body.get('password'), self.transport)
                return self.reply(200, {'csrf': csrf}, cookie=self.session_cookie(token, 3600))
            if self.path == '/api/logout':
                with self.app.auth_lock: self.app.sessions.pop(token, None)
                return self.reply(200, {'message':'Signed out.'}, cookie=self.session_cookie('', 0))
            if self.path == '/api/action': return self.reply(200, self.app.execute(body))
            if self.path == '/api/password': return self.reply(200, self.app.change_password(body))
            raise PanelError(404, 'Not found.')
        except PanelError as e: self.reply(e.code, {'error': e.message})
        except (OSError, ValueError, TypeError): self.reply(503, {'error':'Operation unavailable. Inspect router state.'})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, app, assets, context=None):
        self.app, self.assets, self.context = app, Path(assets), context
        self.slots = app.slots
        super().__init__(address, Handler)
    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(10)
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
        try:
            # Detect TLS inside the bounded worker, never in the accept loop.
            # MSG_PEEK leaves the first byte for TLS or the HTTP parser to consume.
            if self.context and request.recv(1, socket.MSG_PEEK) == b'\x16':
                request = self.context.wrap_socket(request, server_side=True, do_handshake_on_connect=False)
            super().process_request_thread(request, address)
        except (OSError, ValueError):
            self.shutdown_request(request)
        finally: self.slots.release()
    def handle_error(self, request, client_address): pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--restore-failover', action='store_true')
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
        print('Configured http://'+args.bind+':'+str(args.port)+' and https://'+args.bind+':'+str(args.port))
        print('Self-signed certificate: compare the SHA256 fingerprint before trusting it:')
        rc, fingerprint = command(['/opt/bin/openssl','x509','-in',str(folder/'cert.pem'),'-noout','-fingerprint','-sha256'])
        print(fingerprint.strip())
        return
    settings = json.loads(config.read_text())
    app = Application(settings)
    if args.restore_failover:
        if app.failover.record(): app.failover.reset()
        return
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config.parent/'cert.pem', config.parent/'key.pem')
    with Server((settings['bind'], settings['port']), app, Path(__file__).parent, context) as server:
        def shutdown(*_):
            app.failover.stop.set()
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, shutdown)
        worker = threading.Thread(target=app.failover.run, name='awg3-failover', daemon=True)
        worker.start()
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            app.failover.stop.set()
            # Finish/roll back the routing transaction before exiting; never leave
            # a detached ndmc command changing routes after the journal is restored.
            worker.join()
            if app.failover.record(): app.failover.reset()

if __name__ == '__main__':
    try: main()
    except (PanelError, ValueError, OSError) as exc:
        print('Panel setup/start failed:', exc.message if isinstance(exc, PanelError) else str(exc))
        raise SystemExit(1)
