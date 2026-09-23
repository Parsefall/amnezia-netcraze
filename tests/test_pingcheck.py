"""Synthetic firmware tests: no router required or contacted."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('panel', Path(__file__).resolve().parents[1]/'web/server.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

class PingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base/'conf').mkdir()
        (self.base/'conf/pars.conf').touch()
        (self.base/'managed.tsv').write_text(str(self.base/'conf/pars.conf')+'\t0\tOpkgTun0\n')
        self.config = 'interface OpkgTun0\n    ping-check profile AWG3Check\n    ping-check restart\n!\ninterface ISP\n    ping-check profile AWG3Check\n!\nsecret NEVER_RETURN_THIS\n'
        self.calls = []
        self.fail = None
        self.app = w.Application({'bind':'192.168.1.1','network':'192.168.1.0/24','port':8088}, self.base, self.runner, self.base/'run')
        self.body = {'action':'pingcheck-apply','interface':'OpkgTun0','host':'1.1.1.1','update-interval':10,'timeout':3,'max-fails':3,'min-success':2}
    def tearDown(self): self.tmp.cleanup()
    def runner(self, args, timeout=75):
        cmd = args[2]
        self.calls.append(cmd)
        if cmd == 'show running-config': return 0, self.config
        if self.fail and self.fail(cmd): return 0, 'Command::Base error[7405602]: argument parse error.'
        return 0, 'OK'
    def test_interface_scoped_status(self):
        output = """    pingcheck:
          profile: default
        interface:
                 name: ISP
               status: pass
    pingcheck:
          profile: AWG3Check
        interface:
                 name: OpkgTun0
          ignore-fail: no
         successcount: 0
            failcount: 3
               status: fail
        interface:
                 name: OpkgTun1
               status: pass
"""
        self.assertEqual(w.ping_states(output), {'OpkgTun0':'fail', 'OpkgTun1':'pass'})
        self.assertEqual(w.ping_states('profile: AWG3Check\nstatus: pass'), {})
    def test_connection_and_saved_display_name(self):
        original = self.app.runner
        def runner(args, timeout=75):
            if args[0] == w.AWG: return 0, 'key 123 456'
            if args[-1] == 'show ping-check': return 0, 'interface:\n name: OpkgTun0\n status: pass'
            return original(args,timeout)
        self.app.runner=runner
        (self.base/'names').mkdir();(self.base/'names/pars').write_text('My VPN')
        self.app.runpath.mkdir();(self.app.runpath/'running').touch()
        status=self.app.status()
        self.assertTrue(status['running'])
        self.assertEqual(status['tunnels'][0]['name'],'My VPN')
        self.assertEqual(status['tunnels'][0]['connection'],'connected')
        (self.app.runpath/'running').unlink()
        self.assertFalse(self.app.status()['running'])
        self.assertEqual(self.app.status()['tunnels'][0]['connection'],'disconnected')
        self.app.runner=lambda args, timeout=75: (1, '')
        self.assertEqual(self.app.status()['tunnels'][0]['connection'],'disconnected')
    def test_rename_validation(self):
        for label in ['bad"name', '../escape', 'x;reboot', '', 'x\nup']:
            with self.assertRaises(w.PanelError): self.app.execute({'action':'rename','name':'pars','label':label})
        self.assertEqual(self.calls, [])
    def test_apply_preserves_shared_profile_and_does_not_save(self):
        result = self.app.execute(self.body)
        created = self.calls[1].split()[-1]
        self.assertTrue(created.startswith('AWG3Web0_'))
        self.assertIn('ping-check profile '+created+' min-success 2', self.calls)
        self.assertEqual(self.calls[-2:], ['interface OpkgTun0 ping-check profile '+created, 'interface OpkgTun0 no ping-check restart'])
        self.assertFalse(any(c.startswith('no ping-check profile AWG3Check') for c in self.calls))
        self.assertNotIn('system configuration save', self.calls)
        self.assertNotIn('NEVER_RETURN', str(result))
        self.assertFalse((self.base/'run/service.lock').exists())
    def test_disable_detaches_only_interface(self):
        self.app.execute({'action':'pingcheck-disable','interface':'OpkgTun0'})
        self.assertEqual(self.calls[-1], 'interface OpkgTun0 no ping-check profile')
        self.assertEqual(len(self.calls),2)
    def test_save_explicit(self):
        self.app.execute({'action':'pingcheck-save'})
        self.assertEqual(self.calls, ['system configuration save'])
    def test_unmanaged_interface(self):
        for iface in ['ISP','OpkgTun1','OpkgTun0; reboot',None]:
            with self.assertRaises(w.PanelError): self.app.execute(dict(self.body,interface=iface))
        self.assertEqual(self.calls, [])
    def test_validation_before_commands(self):
        for change in [{'host':'1.1.1.1; reboot'},{'host':'::1'},{'host':'127.0.0.1'},{'timeout':10},{'max-fails':True},{'min-success':0},{'update-interval':3601}]:
            with self.assertRaises(w.PanelError): self.app.execute(dict(self.body,**change))
        self.assertEqual(self.calls, [])
    def test_service_lock(self):
        lock=self.base/'run/service.lock';lock.mkdir(parents=True)
        with self.assertRaises(w.PanelError) as error: self.app.execute(self.body)
        self.assertEqual(error.exception.code,409)
        self.assertTrue(lock.exists());self.assertEqual(self.calls,[])
    def test_setup_error_keeps_previous_assignment(self):
        self.fail=lambda cmd: ' mode icmp' in cmd
        with self.assertRaises(w.PanelError): self.app.execute(self.body)
        self.assertFalse(any(c.startswith('interface ') for c in self.calls))
        self.assertTrue(self.calls[-1].startswith('no ping-check profile AWG3Web'))
    def test_assignment_error_restores_previous_restart(self):
        self.fail=lambda cmd: cmd == 'interface OpkgTun0 no ping-check restart'
        with self.assertRaises(w.PanelError): self.app.execute(self.body)
        self.assertIn('interface OpkgTun0 ping-check profile AWG3Check', self.calls)
        self.assertIn('interface OpkgTun0 ping-check restart', self.calls)
        self.assertFalse((self.base/'run/service.lock').exists())
    def test_failed_rollback_reported(self):
        self.fail=lambda cmd: cmd.startswith('interface ')
        with self.assertRaises(w.PanelError) as error: self.app.execute(self.body)
        self.assertEqual(error.exception.code,500)
        self.assertIn('rollback', error.exception.message)
        self.assertFalse(any(c.startswith('no ping-check profile ') for c in self.calls))
    def test_absent_interface_refused(self):
        self.config = 'interface ISP\n    description Internet\n!\n'
        with self.assertRaises(w.PanelError): self.app.execute(self.body)
        self.assertEqual(self.calls,['show running-config'])
    def test_unused_panel_profile_cleanup(self):
        self.config='interface OpkgTun0\n    ping-check profile AWG3Web0_1234abcd\n!\n'
        self.app.execute(self.body)
        self.assertEqual(self.calls[-1], 'no ping-check profile AWG3Web0_1234abcd')
    def test_shared_panel_profile_not_deleted(self):
        self.config=self.config.replace('AWG3Check','AWG3Web0_1234abcd')
        self.app.execute(self.body)
        self.assertNotIn('no ping-check profile AWG3Web0_1234abcd',self.calls)

if __name__ == '__main__': unittest.main()
