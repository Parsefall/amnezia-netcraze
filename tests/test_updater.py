import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('updater',Path(__file__).resolve().parents[1]/'web/updater.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.base=self.root/'opt/etc/awg3';self.run=self.root/'run';self.run.mkdir()
        self.job=self.base/'updates/job-test';self.job.mkdir(parents=True)
        self.old={}
        for source,dest in u.FILES.items():
            data=b'# old file\n'
            if source=='web/VERSION':data=b'1.0.0\n'
            if source=='web/UPDATE_FORMAT':data=b'1\n'
            path=self.root/dest;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);self.old[dest]=data
        for source,dest in u.ENGINES.items():(self.root/dest).write_bytes(b'unchanged-engine')
        (self.base/'conf').mkdir();(self.base/'conf/private.conf').write_text('SECRET-PROFILE')
        (self.base/'web').mkdir();(self.base/'web/settings.json').write_text('SECRET-SETTINGS')
        self.archive=self.root/'input.tar.gz';self.checksum=self.root/'input.sha256';self.count=0
        self.package()
    def tearDown(self):self.tmp.cleanup()
    def payload(self):
        result={name:b'# new file\n' for name in u.FILES}
        result.update({name:b'unchanged-engine' for name in u.ENGINES})
        result['web/VERSION']=b'1.1.0\n';result['web/UPDATE_FORMAT']=b'1\n'
        return result
    def package(self,changes=None,extra=None,bad_manifest=False):
        values=self.payload();values.update(changes or {})
        manifest=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(values.items()))
        if bad_manifest:manifest=manifest.replace(hashlib.sha256(values['web/app.js']).hexdigest(),'0'*64,1)
        values['SHA256SUMS']=manifest.encode()
        with tarfile.open(self.archive,'w:gz') as tar:
            for name,data in values.items():
                item=tarfile.TarInfo('awg3-userspace/'+name);item.size=len(data);tar.addfile(item,io.BytesIO(data))
            if extra:
                tar.addfile(extra,io.BytesIO(b'x'*extra.size) if extra.isfile() else None)
        self.checksum.write_text(u.digest(self.archive)+'  '+u.ASSET+'\n')
    def stage(self):
        self.count+=1;path=self.root/('stage'+str(self.count))
        u.verified_stage(self.archive,self.checksum,path,'v1.1.0',self.root)
        return path
    def release(self):
        prefix='https://github.com/'+u.REPO+'/releases/download/v1.1.0/'
        return u.parse_release({'tag_name':'v1.1.0','draft':False,'prerelease':False,'assets':[
            {'name':name,'browser_download_url':prefix+name,'state':'uploaded','size':100}
            for name in (u.ASSET,u.ASSET+'.sha256')]})
    def setup_job(self):
        release=self.release();u.atomic_json(self.job/'job.json',{'current':'1.0.0','release':release})
        u.atomic_json(self.base/'updates/state.json',{'phase':'queued','target':'v1.1.0'})
        (self.run/'update.lock').mkdir()
    def fetch(self,url,target,limit):shutil.copyfile(self.checksum if url.endswith('.sha256') else self.archive,target)
    def job_run(self,command=lambda args:None,health=lambda base,version:None):
        self.setup_job();u.run_job(self.job,self.base,self.run,self.root,self.fetch,command,health)
        return u.read_json(self.base/'updates/state.json')
    def assert_old(self):
        for dest,data in self.old.items():self.assertEqual((self.root/dest).read_bytes(),data,dest)
        self.assertEqual((self.base/'conf/private.conf').read_text(),'SECRET-PROFILE')
        self.assertEqual((self.base/'web/settings.json').read_text(),'SECRET-SETTINGS')
    def test_valid_package_and_manifest(self):
        path=self.stage();self.assertEqual((path/'web/VERSION').read_text(),'1.1.0\n')
        self.assertFalse((path/'prebuilt').exists())
    def test_checksums(self):
        self.checksum.write_text('0'*64+'  '+u.ASSET+'\n')
        with self.assertRaisesRegex(u.UpdateError,'archive_checksum'):self.stage()
        self.package(bad_manifest=True)
        with self.assertRaisesRegex(u.UpdateError,'file_checksum'):self.stage()
        self.assert_old()
    def test_untrusted_archive_members(self):
        for name,kind in [('awg3-userspace/../../outside',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),('awg3-userspace/web/app.js',tarfile.REGTYPE),('awg3-userspace/link',tarfile.SYMTYPE),('awg3-userspace/hard',tarfile.LNKTYPE)]:
            with self.subTest(name=name):
                member=tarfile.TarInfo(name);member.type=kind;member.size=1 if kind==tarfile.REGTYPE else 0;member.linkname='/etc/passwd'
                self.package(extra=member)
                with self.assertRaisesRegex(u.UpdateError,'unsafe_archive'):self.stage()
    def test_new_engine_requires_manual_update(self):
        self.package({'prebuilt/kn-1012/amneziawg-go':b'new engine'})
        result=self.job_run();self.assertEqual(result['error'],'engine_changed_manual_update_required');self.assert_old()
    def test_format_and_version_rejected(self):
        self.package({'web/UPDATE_FORMAT':b'2'})
        with self.assertRaisesRegex(u.UpdateError,'manual_update'):self.stage()
        self.package({'web/VERSION':b'99.0.0'})
        with self.assertRaisesRegex(u.UpdateError,'version_mismatch'):self.stage()
    def test_invalid_python_rejected_before_install(self):
        self.package({'web/server.py':b'if broken:'})
        with self.assertRaises(SyntaxError):self.stage()
        self.assert_old()
    def test_url_and_version_validation(self):
        for url in ['http://github.com/x','https://evil.test/x','https://github.com.evil.test/x','https://name@github.com/x','https://github.com:444/x']:
            with self.assertRaises(u.UpdateError):u.allowed_url(url)
        for tag in ['main','v1.2.3;reboot','v1.2.3-beta','01.2.3']:
            with self.assertRaises(u.UpdateError):u.version(tag)
        self.assertGreater(u.version('v1.10.0'),u.version('v1.9.0'))
    def test_release_fixed_asset_locations(self):
        self.assertEqual(self.release()['tag'],'v1.1.0')
        with self.assertRaises(u.UpdateError):u.parse_release({'tag_name':'v1.1.0','assets':[]})
        with self.assertRaises(u.UpdateError):u.parse_release({'tag_name':'v1.1.0','prerelease':True})
    def test_transaction_preserves_profiles_and_engines(self):
        calls=[];versions=[]
        result=self.job_run(calls.append,lambda base,v:versions.append(v))
        self.assertEqual(result['phase'],'complete');self.assertEqual(versions,['1.1.0'])
        self.assertTrue((self.job/'backup/files.json').is_file())
        self.assertEqual((self.base/'conf/private.conf').read_text(),'SECRET-PROFILE')
        self.assertEqual((self.base/'web/settings.json').read_text(),'SECRET-SETTINGS')
        self.assertEqual((self.root/'opt/bin/amneziawg-go').read_bytes(),b'unchanged-engine')
        self.assertFalse(any('S99awg3' in arg for call in calls for arg in call))
        self.assertFalse((self.run/'service.lock').exists());self.assertFalse((self.run/'update.lock').exists())
        self.assertFalse((self.job/'package.tar.gz').exists())
    def test_health_failure_rolls_back(self):
        def check(base,v):
            if v=='1.1.0':raise u.UpdateError('panel_healthcheck_failed')
        result=self.job_run(health=check)
        self.assertEqual(result['phase'],'rolled_back');self.assert_old()
    def test_partial_file_failure_rolls_back(self):
        original=u.atomic_copy;failed=False
        def copy(source,target,mode):
            nonlocal failed
            if target.name=='app.js' and not failed:failed=True;raise OSError('synthetic disk error')
            return original(source,target,mode)
        with patch.object(u,'atomic_copy',copy):result=self.job_run()
        self.assertEqual(result['phase'],'rolled_back');self.assert_old()
    def test_rollback_failure_visible(self):
        def broken(base,v):raise u.UpdateError('panel_healthcheck_failed')
        result=self.job_run(health=broken)
        self.assertEqual(result['phase'],'rollback_failed')
        self.assertTrue((self.job/'backup/files.json').exists())
    def test_service_lock_preserved(self):
        (self.run/'service.lock').mkdir();(self.run/'service.lock/pid').write_text('other')
        result=self.job_run();self.assertEqual(result['error'],'vpn_service_busy')
        self.assertEqual((self.run/'service.lock/pid').read_text(),'other');self.assert_old()
    def test_not_enough_space(self):
        class Space:free=0
        with patch.object(u.shutil,'disk_usage',return_value=Space()):result=self.job_run()
        self.assertEqual(result['error'],'not_enough_storage');self.assert_old()
    def test_manager_requires_checked_version_and_detaches(self):
        calls=[]
        class Process:pid=os.getpid()
        def launch(args,**kwargs):calls.append((args,kwargs));return Process()
        appdir=Path(__file__).resolve().parents[1]/'web'
        manager=u.Manager(self.base,self.run,appdir,launch=launch)
        manager.current=lambda:'1.0.0'
        with self.assertRaisesRegex(u.UpdateError,'check_update_first'):manager.start('v1.1.0')
        u.atomic_json(self.base/'updates/available.json',self.release())
        result=manager.start('v1.1.0');self.assertTrue(result['active'])
        self.assertTrue(calls[0][1]['start_new_session']);self.assertEqual(calls[0][0][-1],'--run')
        with self.assertRaisesRegex(u.UpdateError,'update_busy'):manager.start('v1.1.0')
    def test_interrupted_install_requires_recovery(self):
        manager=u.Manager(self.base,self.run,self.root/'opt/lib/awg3/web')
        u.atomic_json(self.base/'updates/available.json',self.release())
        u.atomic_json(self.base/'updates/state.json',{'phase':'installing'})
        self.assertEqual(manager.status()['progress']['phase'],'interrupted')
        with self.assertRaisesRegex(u.UpdateError,'interrupted_manual_recovery'):manager.start('v1.1.0')
    def test_interrupted_download_can_retry(self):
        class Process:pid=os.getpid()
        manager=u.Manager(self.base,self.run,self.root/'opt/lib/awg3/web',launch=lambda *a,**k:Process())
        u.atomic_json(self.base/'updates/available.json',self.release())
        u.atomic_json(self.base/'updates/state.json',{'phase':'downloading'})
        self.assertTrue(manager.start('v1.1.0')['active'])
    def test_spawn_failure_releases_lock(self):
        def fail(*args,**kwargs):raise OSError('synthetic spawn error')
        manager=u.Manager(self.base,self.run,self.root/'opt/lib/awg3/web',launch=fail)
        u.atomic_json(self.base/'updates/available.json',self.release())
        with self.assertRaises(OSError):manager.start('v1.1.0')
        self.assertFalse((self.run/'update.lock').exists())
        self.assertEqual(manager.status()['progress']['phase'],'failed')

if __name__=='__main__':unittest.main()
