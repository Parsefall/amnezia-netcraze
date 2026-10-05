"""Routing state machine tests with a mutable firmware model; no real router."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('panel_failover', Path(__file__).resolve().parents[1]/'web/server.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class FailoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base/'conf').mkdir()
        (self.base/'run').mkdir()
        (self.base/'run/running').touch()
        for name in ('a','b','c'):
            (self.base/'conf'/(name+'.conf')).touch()
        (self.base/'managed.tsv').write_text(''.join(str(self.base/'conf'/(n+'.conf'))+'\t'+str(i)+'\tOpkgTun'+str(i)+'\n' for i,n in enumerate(('a','b','c'))))
        self.health = ['pass','pass','pass']
        self.assignments = {0,1,2}
        self.calls = []
        self.failure = None
        self.fail_once = False
        self.allowed = '0.0.0.0/0'
        self.dns_upsert = False
        self.policy_renumber = False
        self.now = 100.0
        self.rules = {}
        self.add('ip route 203.0.113.0 255.255.255.0 OpkgTun0 auto reject')
        self.add('ip route 198.51.100.0 255.255.255.0 OpkgTun2 auto')
        self.app = w.Application({'bind':'192.168.1.1','network':'192.168.1.0/24','port':8088}, self.base, self.runner, self.base/'run')
        self.app.failover.clock = lambda:self.now

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, command):
        rule = w.FailoverRule(command)
        if rule.kind == 'dns' and self.dns_upsert:
            self.rules = {k:r for k,r in self.rules.items() if r.prefix != rule.prefix}
        if rule.kind == 'policy' and self.policy_renumber:
            members = sorted((r for r in self.rules.values() if r.prefix == rule.prefix and r.key != rule.key), key=lambda r:int(r.suffix[-1]))
            members.insert(int(rule.suffix[-1]),rule)
            self.rules = {k:r for k,r in self.rules.items() if r.prefix != rule.prefix}
            for order,member in enumerate(members):
                new = w.FailoverRule(' '.join(member.prefix+[member.iface,'order',str(order)]))
                self.rules[new.key] = new
            return
        self.rules[rule.key] = rule

    def config(self):
        return ''.join('interface OpkgTun'+str(i)+'\n    ip global auto\n'+('    ping-check profile Check'+str(i)+'\n' if i in self.assignments else '')+'!\n' for i in range(3)) + '\n'.join(r.command for r in self.rules.values()) + '\nsecret NEVER_WRITE_THIS\n'

    def runner(self, args, timeout=75):
        self.calls.append(args)
        if args[0] == w.AWG:
            if args[-1] == 'allowed-ips': return 0,'peer '+self.allowed
            return 0, 'peer 123 456' if args[-1] == 'transfer' else 'peer 123'
        if args[0] != 'ndmc': return 0, 'OK'
        cmd = args[-1]
        if cmd == 'show running-config': return 0, self.config()
        if cmd == 'show ping-check':
            return 0, '\n'.join('interface:\n name: OpkgTun'+str(i)+'\n status: '+s for i,s in enumerate(self.health))
        if self.failure and self.failure(cmd):
            if self.fail_once: self.failure = None
            return 0, 'Command::Base error[123]: rejected'
        if cmd.startswith('ip policy ') and ' no permit global ' in cmd:
            normalized = cmd.replace(' no permit global ', ' permit global ')
            rule = w.FailoverRule(normalized)
            self.rules.pop(rule.key, None)
            if self.policy_renumber:
                members = sorted((r for r in self.rules.values() if r.prefix == rule.prefix),key=lambda r:int(r.suffix[-1]))
                for order,member in enumerate(members):
                    self.add(' '.join(member.prefix+[member.iface,'order',str(order)]))
        elif cmd.startswith('no '):
            rule = w.FailoverRule(cmd[3:])
            self.rules.pop(rule.key, None)
        else:
            self.add(cmd)
        return 0, 'OK'

    def configure(self, source='a', target='b'):
        return self.app.execute({'action':'failover-set','name':source,'backup':target})

    def commands(self):
        return [c[-1] for c in self.calls if c[0] == 'ndmc' and not c[-1].startswith('show ')]

    def route(self, iface=0):
        return 'ip route 203.0.113.0 255.255.255.0 OpkgTun'+str(iface)+' auto reject'

    def active_routes(self):
        return {r.command for r in self.rules.values()}

    def fail(self):
        self.health[0] = 'fail'
        self.app.failover.tick()
        self.assertEqual(self.app.failover.error, '')

    def test_failure_switches_only_owned_routes_and_returns_after_stable_success(self):
        self.configure()
        self.calls.clear()
        self.app.failover.tick()
        self.assertEqual(self.commands(), [])
        self.fail()
        self.assertIn(self.route(1), self.active_routes())
        self.assertNotIn(self.route(), self.active_routes())
        self.assertIn('ip route 198.51.100.0 255.255.255.0 OpkgTun2 auto', self.active_routes())
        self.assertFalse(any('save' in c or 'interface ' in c for c in self.commands()))
        self.assertEqual(self.app.status()['tunnels'][0]['via'], 'b')
        count = len(self.commands())
        self.app.failover.tick()
        self.assertEqual(len(self.commands()), count)
        self.health[0] = 'pass'
        self.app.failover.tick()
        self.now += 29
        self.app.failover.tick()
        self.assertIn(self.route(1), self.active_routes())
        self.now += 1
        self.app.failover.tick()
        self.assertIn(self.route(), self.active_routes())
        self.assertNotIn(self.route(1), self.active_routes())
        self.assertFalse(self.app.failover.journal.exists())

    def test_unknown_or_failed_backup_does_not_receive_traffic(self):
        self.configure()
        for value in ('fail', 'unknown'):
            self.health = ['fail',value,'pass']
            self.app.failover.tick()
            self.assertIn(self.route(), self.active_routes())
            self.assertNotIn(self.route(1), self.active_routes())

    def test_unknown_primary_never_triggers_failover(self):
        self.configure()
        self.health[0] = 'unknown'
        self.app.failover.tick()
        self.assertIn(self.route(), self.active_routes())

    def test_manual_stop_is_not_an_outage(self):
        self.configure()
        (self.base/'paused').mkdir()
        (self.base/'paused/a').touch()
        self.fail()
        self.assertIn(self.route(), self.active_routes())
        (self.base/'paused/a').unlink()
        self.fail()
        (self.base/'run/running').unlink()
        self.app.failover.tick()
        self.assertIn(self.route(), self.active_routes())

    def test_backup_failure_restores_original_behavior(self):
        self.configure(); self.fail()
        self.health[1] = 'fail'
        self.app.failover.tick()
        self.assertIn(self.route(), self.active_routes())
        self.assertFalse(self.app.failover.journal.exists())

    def test_chain_and_cycle_validation(self):
        self.configure('b', None)
        self.add('ip route 192.0.2.1 OpkgTun1 auto')
        self.configure('b','c')
        self.configure()
        with self.assertRaisesRegex(w.PanelError, 'failover_cycle'): self.configure('c','a')
        with self.assertRaises(w.PanelError): self.configure('a','a')
        self.health = ['fail','fail','pass']
        self.app.failover.tick()
        self.assertIn(self.route(2), self.active_routes())
        self.assertEqual(self.app.status()['tunnels'][0]['via'], 'c')

    def test_disabling_restores_routes_before_saving_choice(self):
        self.configure(); self.fail()
        self.configure('a',None)
        self.assertEqual(self.app.failover.pairs(), {})
        self.assertIn(self.route(), self.active_routes())

    def test_dns_group_and_explicit_policy(self):
        dns = 'dns-proxy route object-group domain-list0 OpkgTun0 auto reject'
        policy = 'ip policy Policy0 permit global OpkgTun0 order 0'
        self.add(dns); self.add(policy)
        self.configure(); self.fail()
        self.assertIn(dns.replace('OpkgTun0','OpkgTun1'), self.active_routes())
        self.assertIn(policy.replace('OpkgTun0','OpkgTun1'), self.active_routes())
        self.app.failover.reset()
        self.assertIn(dns,self.active_routes())
        self.assertIn(policy,self.active_routes())

    def test_existing_backup_route_is_never_removed_on_restore(self):
        self.add(self.route(1))
        self.configure(); self.fail()
        self.app.failover.reset()
        self.assertIn(self.route(1), self.active_routes())
        self.assertIn(self.route(), self.active_routes())

    def test_dns_single_destination_firmware(self):
        self.dns_upsert = True
        self.test_dns_group_and_explicit_policy()

    def test_backup_must_cover_the_destinations(self):
        self.configure()
        self.allowed = '192.0.2.0/24'
        self.health[0] = 'fail'
        self.calls.clear()
        self.app.failover.tick()
        self.assertEqual(self.app.failover.error,'failover_backup_coverage')
        self.assertEqual(self.commands(),[])

    def policy_setup(self):
        self.policy_renumber = True
        for i,iface in enumerate(('OpkgTun0','OpkgTun1','OpkgTun2','GigabitEthernet1')):
            self.add('ip policy Policy0 permit global '+iface+' order '+str(i))

    def test_policy_with_existing_backup_and_renumbering(self):
        self.policy_setup()
        original = self.active_routes()
        self.configure(); self.fail()
        self.assertIn('ip policy Policy0 permit global OpkgTun1 order 0',self.active_routes())
        self.assertIn('ip policy Policy0 permit global GigabitEthernet1 order 2',self.active_routes())
        self.app.failover.reset()
        self.assertEqual(self.active_routes(),original)

    def test_interrupted_policy_renumbering_rolls_back_every_member(self):
        self.policy_setup()
        original = self.active_routes()
        self.configure()
        self.failure = lambda cmd:cmd == 'ip policy Policy0 permit global OpkgTun1 order 0'
        self.fail_once = True
        self.health[0] = 'fail'
        self.app.failover.tick()
        self.assertEqual(self.active_routes(),original)
        self.assertFalse(self.app.failover.journal.exists())

    def test_partial_failure_rolls_back(self):
        original = self.active_routes()
        self.configure()
        self.failure = lambda cmd:cmd.startswith('no ip route')
        self.fail_once = True
        self.health[0] = 'fail'
        self.app.failover.tick()
        self.assertTrue(self.app.failover.error)
        self.assertEqual(self.active_routes(),original)
        self.assertFalse(self.app.failover.journal.exists())

    def test_command_applied_but_timeout_is_recovered(self):
        self.configure()
        runner = self.app.runner
        fired = False
        def timeout(args, timeout=75):
            nonlocal fired
            result = runner(args,timeout)
            if args[-1] == self.route(1) and not fired:
                fired = True
                raise w.PanelError(504,'timeout')
            return result
        self.app.runner = timeout
        self.health[0] = 'fail'
        self.app.failover.tick()
        self.assertIn(self.route(),self.active_routes())
        self.assertNotIn(self.route(1),self.active_routes())

    def test_pending_journal_recovers_after_restart(self):
        self.configure(); self.fail()
        record = self.app.failover.record();record['phase']='pending'
        w.private_json(self.app.failover.journal,record)
        self.app.failover = w.Failover(self.app,lambda:self.now)
        self.health[0] = 'pass'
        self.app.failover.tick()
        self.assertIn(self.route(),self.active_routes())
        self.assertFalse(self.app.failover.journal.exists())

    def test_interrupted_return_keeps_recoverable_journal(self):
        self.policy_setup()
        original = self.active_routes()
        self.configure(); self.fail()
        self.failure = lambda cmd: cmd == self.route()
        self.fail_once = True
        with self.assertRaises(w.PanelError): self.app.failover.reset()
        self.assertEqual(self.app.failover.record()['phase'], 'pending')
        self.health[0] = 'pass'
        self.app.failover = w.Failover(self.app, lambda:self.now)
        self.app.failover.tick()
        self.assertEqual(self.active_routes(), original)
        self.assertFalse(self.app.failover.journal.exists())

    def test_policy_order_does_not_depend_on_interface_names(self):
        self.policy_renumber = True
        for order,iface in enumerate(('OpkgTun2','GigabitEthernet1','OpkgTun0','OpkgTun1')):
            self.add('ip policy Policy0 permit global '+iface+' order '+str(order))
        original = self.active_routes()
        self.configure(); self.fail()
        self.assertIn('ip policy Policy0 permit global OpkgTun1 order 2', self.active_routes())
        self.app.failover.reset()
        self.assertEqual(self.active_routes(), original)

    def test_reboot_with_original_startup_routes(self):
        self.configure(); self.fail()
        self.rules.pop(w.FailoverRule(self.route(1)).key)
        self.add(self.route())
        self.health[0] = 'pass'
        self.app.failover = w.Failover(self.app,lambda:self.now)
        self.app.failover.tick()
        self.assertFalse(self.app.failover.journal.exists())
        self.assertEqual(self.app.failover.error,'')

    def test_external_route_change_is_not_overwritten(self):
        self.configure(); self.fail()
        self.add(self.route(1).replace(' auto reject',' auto'))
        self.calls.clear()
        self.app.failover.tick()
        self.assertEqual(self.app.failover.error,'failover_route_conflict')
        self.assertEqual(self.commands(),[])
        self.assertTrue(self.app.failover.journal.exists())

    def test_locks_and_update_suppress_routing_writes(self):
        self.configure(); self.health[0]='fail'
        for lock in ('service.lock','update.lock'):
            folder=self.base/'run'/lock;folder.mkdir()
            self.calls.clear();self.app.failover.tick()
            self.assertEqual(self.commands(),[])
            folder.rmdir()
        self.app.operation.acquire()
        try:
            self.calls.clear();self.app.failover.tick()
            self.assertEqual(self.calls,[])
        finally:self.app.operation.release()

    def test_protect_pingcheck_delete_and_firmware_save(self):
        self.configure()
        for body in ({'action':'delete','name':'b'}, {'action':'pingcheck-disable','interface':'OpkgTun0'}):
            with self.assertRaises(w.PanelError):self.app.execute(body)
        self.fail()
        with self.assertRaises(w.PanelError):self.app.execute({'action':'pingcheck-save'})

    def test_configuration_validation_and_journal_contains_no_secrets(self):
        for value in ('a; reboot','missing',123,[]):
            with self.assertRaises(w.PanelError):self.configure('a',value)
        self.assignments.remove(1)
        with self.assertRaises(w.PanelError):self.configure()
        self.assignments.add(1)
        self.configure();self.fail()
        self.assertNotIn('NEVER_WRITE_THIS',self.app.failover.journal.read_text())
        self.assertEqual(self.app.failover.pairs(),{'a':'b'})


class RuleTests(unittest.TestCase):
    def test_route_with_unrecognized_child_is_unsupported(self):
        _,unsupported = w.routing_rules('ip route 203.0.113.1 OpkgTun0 auto\n    disable\n')
        self.assertEqual(unsupported, {'OpkgTun0'})

    def test_nested_config_and_masks(self):
        rules, unsupported = w.routing_rules('ip policy Policy0\n    route 203.0.113.0 /24 OpkgTun0 auto reject\n    permit global OpkgTun0 order 0\n!\ndns-proxy\n    route object-group sites OpkgTun0 auto\n!\n')
        self.assertEqual(len(rules),3)
        self.assertFalse(unsupported)
        self.assertIn('ip policy Policy0 route 203.0.113.0 255.255.255.0 OpkgTun0 auto reject',{r.command for r in rules.values()})

    def test_unknown_gateway_and_injection_are_rejected(self):
        for line in ('ip route 203.0.113.1 10.0.0.1 OpkgTun0', 'ip route default OpkgTun0; reboot', 'dns-proxy route object-group sites OpkgTun0 auto; reboot'):
            with self.assertRaises((ValueError,IndexError)):w.FailoverRule(line)
        _,unsupported=w.routing_rules('ip route 203.0.113.1 10.0.0.1 OpkgTun0')
        self.assertEqual(unsupported,{'OpkgTun0'})


if __name__ == '__main__':unittest.main()
