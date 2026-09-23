"""Fixed-repository, bounded, transactional hot updates. Never installs VPN binaries."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

REPO = 'Parsefall/amnezia-netcraze'
API = 'https://api.github.com/repos/'+REPO+'/releases/latest'
ASSET = 'awg3-netcraze-arm64-userspace.tar.gz'
BASE = Path('/opt/etc/awg3')
RUN = Path('/var/run/awg3')
MAX_DOWNLOAD = 32*1024*1024
MAX_EXPANDED = 128*1024*1024
HOSTS = {'api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}
# Changes to this deployment contract require a new UPDATE_FORMAT.
FILES = {**{'web/'+f:'opt/lib/awg3/web/'+f for f in
          ('server.py','app.js','index.html','style.css','updater.py','VERSION','UPDATE_FORMAT')},
         **{'router/opt/etc/init.d/'+f:'opt/etc/init.d/'+f for f in ('S99awg3','S100awg3-watchdog','S101awg3-web')},
         'router/opt/bin/awg3-split-config':'opt/bin/awg3-split-config',
         'tools/convert_profile.py':'opt/lib/awg3/convert_profile.py'}
ENGINES = {'prebuilt/kn-1012/awg':'opt/bin/awg','prebuilt/kn-1012/amneziawg-go':'opt/bin/amneziawg-go'}
TERMINAL = {'idle','complete','failed','rolled_back','rollback_failed','interrupted'}

class UpdateError(Exception): pass

def version(text):
    if not isinstance(text,str) or not re.fullmatch(r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',text):
        raise UpdateError('invalid_version')
    return tuple(map(int,text.lstrip('v').split('.')))

def read_json(path, default=None):
    try:
        if path.stat().st_size > 1024*1024: raise UpdateError('invalid_state')
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError: return {} if default is None else default

def atomic_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.state-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def allowed_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.port not in (None,443) or p.username or p.password or p.fragment:
        raise UpdateError('untrusted_download_url')
    return url

class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return super().redirect_request(req,fp,code,msg,headers,allowed_url(newurl))

def download(url, destination, limit=MAX_DOWNLOAD):
    allowed_url(url)
    ca=Path('/opt/etc/ssl/certs/ca-certificates.crt')
    context=ssl.create_default_context(cafile=str(ca) if ca.is_file() else None)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),Redirects(),urllib.request.HTTPSHandler(context=context))
    request=urllib.request.Request(url,headers={'User-Agent':'Amnezia-Netcraze-Updater','Accept':'application/vnd.github+json' if url==API else 'application/octet-stream'})
    deadline=time.monotonic()+90
    try:
        with opener.open(request,timeout=15) as response, Path(destination).open('xb') as out:
            allowed_url(response.geturl())
            if int(response.headers.get('Content-Length','0'))>limit: raise UpdateError('download_too_large')
            count=0
            while True:
                block=response.read(65536)
                if not block: break
                count+=len(block)
                if count>limit or time.monotonic()>deadline: raise UpdateError('download_limit')
                out.write(block)
    except UpdateError: raise
    except Exception: raise UpdateError('github_unavailable_check_network_ca_bundle') from None

def parse_release(data):
    tag=data.get('tag_name','')
    version(tag)
    if not tag.startswith('v') or data.get('draft') or data.get('prerelease'): raise UpdateError('stable_release_required')
    assets={x['name']:x for x in data.get('assets',[]) if isinstance(x,dict) and isinstance(x.get('name'),str)}
    prefix='https://github.com/'+REPO+'/releases/download/'+tag+'/'
    result={'tag':tag,'url':'https://github.com/'+REPO+'/releases/tag/'+tag}
    for name,key in [(ASSET,'archive'),(ASSET+'.sha256','checksum')]:
        asset=assets.get(name,{})
        if asset.get('browser_download_url')!=prefix+name or asset.get('state')!='uploaded': raise UpdateError('release_assets_missing')
        size=asset.get('size')
        if type(size) is not int or not 0<size<=MAX_DOWNLOAD: raise UpdateError('download_too_large')
        result[key]=prefix+name
    digest=assets[ASSET].get('digest')
    if digest and not re.fullmatch(r'sha256:[0-9a-f]{64}',digest): raise UpdateError('invalid_digest')
    result['digest']=digest
    return result

def latest(fetch=download):
    with tempfile.TemporaryDirectory(prefix='awg3-release-') as folder:
        path=Path(folder)/'release.json';fetch(API,path,1024*1024)
        try: return parse_release(read_json(path))
        except (ValueError,TypeError,KeyError,AttributeError): raise UpdateError('invalid_release') from None

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(65536),b''): h.update(block)
    return h.hexdigest()

def verified_stage(archive,checksum,stage,tag,root=Path('/'),api_digest=None):
    match=re.fullmatch(r'([0-9a-f]{64})  '+re.escape(ASSET)+r'\s*',Path(checksum).read_text(encoding='ascii'))
    actual=digest(archive)
    if not match or actual!=match[1] or (api_digest and api_digest!='sha256:'+actual): raise UpdateError('archive_checksum_mismatch')
    stage.mkdir(mode=0o700)
    hashes={};manifest=None;total=0
    with tarfile.open(archive,'r:gz') as tar:
        for n,member in enumerate(tar):
            raw=member.name
            parts=PurePosixPath(raw).parts
            if (n>=256 or not raw.startswith('awg3-userspace/') or '\\' in raw
                or '..' in parts or '.' in raw.split('/') or '//' in raw or not member.isfile() or member.issparse()):
                raise UpdateError('unsafe_archive')
            name=raw[len('awg3-userspace/'):]
            if not name or name in hashes or member.size<0 or member.size>64*1024*1024: raise UpdateError('unsafe_archive')
            total+=member.size
            if total>MAX_EXPANDED: raise UpdateError('expanded_package_too_large')
            h=hashlib.sha256();collected=bytearray() if name=='SHA256SUMS' else None
            out=None
            if name in FILES:
                target=stage/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);out=target.open('xb')
            try:
                with tar.extractfile(member) as source:
                    for block in iter(lambda:source.read(65536),b''):
                        h.update(block)
                        if out: out.write(block)
                        if collected is not None:
                            collected.extend(block)
                            if len(collected)>65536: raise UpdateError('manifest_too_large')
            finally:
                if out: out.close()
            hashes[name]=h.hexdigest()
            if collected is not None: manifest=bytes(collected).decode('ascii')
    if manifest is None: raise UpdateError('manifest_missing')
    listed={}
    for line in manifest.splitlines():
        m=re.fullmatch(r'([0-9a-f]{64})  (.+)',line)
        if not m or m[2] in listed: raise UpdateError('invalid_manifest')
        listed[m[2]]=m[1]
    if listed!={k:v for k,v in hashes.items() if k!='SHA256SUMS'}: raise UpdateError('file_checksum_mismatch')
    if not (set(FILES)|set(ENGINES)) <= set(listed): raise UpdateError('package_files_missing')
    if (stage/'web/VERSION').read_text().strip()!=tag.lstrip('v'): raise UpdateError('package_version_mismatch')
    if (stage/'web/UPDATE_FORMAT').read_text().strip()!='1': raise UpdateError('manual_update_required')
    for name,target in ENGINES.items():
        path=root/target
        if not path.is_file() or path.is_symlink() or digest(path)!=hashes[name]: raise UpdateError('engine_changed_manual_update_required')
    for name in FILES:
        if name.endswith('.py'): compile((stage/name).read_bytes(),name,'exec')
    return total

def atomic_copy(source,target,mode):
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.awg3-update-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as out, Path(source).open('rb') as inp:
            shutil.copyfileobj(inp,out,65536);out.flush();os.fsync(out.fileno())
        os.chmod(tmp,mode);os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def run_command(args):
    try:
        result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=35)
        if result.returncode: raise UpdateError('service_command_failed')
    except subprocess.TimeoutExpired: raise UpdateError('service_command_timeout') from None

def health(base,expected):
    settings=read_json(base/'web/settings.json')
    ctx=ssl.create_default_context(cafile=str(base/'web/cert.pem'))
    url='https://'+settings['bind']+':'+str(settings['port'])+'/'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))
    for attempt in range(5):
        try:
            with opener.open(url,timeout=3) as response:
                if response.status==200 and response.headers.get('X-App-Version')==expected: return
        except Exception: pass
        time.sleep(1)
    raise UpdateError('panel_healthcheck_failed')

def install_stage(stage,job,base,root,notify,command=run_command,check_health=health):
    backup=job/'backup';backup.mkdir(mode=0o700)
    records={}
    needed=sum((root/path).stat().st_size for path in FILES.values() if (root/path).is_file())
    if shutil.disk_usage(job).free<needed+8*1024*1024: raise UpdateError('not_enough_storage')
    for source,destination in FILES.items():
        target=root/destination
        if target.is_symlink() or not target.is_file(): raise UpdateError('installed_files_missing_or_symlink')
        saved=backup/source;saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(target,saved)
        records[source]={'mode':target.stat().st_mode & 0o777,'sha256':digest(saved)}
    atomic_json(backup/'files.json',records)
    info=read_json(job/'job.json')
    web=root/'opt/etc/init.d/S101awg3-web';watchdog=root/'opt/etc/init.d/S100awg3-watchdog'
    changed=False;watchdog_stopped=False
    try:
        command([str(watchdog),'stop']);watchdog_stopped=True
        command([str(web),'stop'])
        notify('installing',backup=str(backup))
        changed=True
        for source,destination in FILES.items():
            mode=0o755 if destination.startswith('opt/etc/init.d/') or destination=='opt/bin/awg3-split-config' else 0o600
            atomic_copy(stage/source,root/destination,mode)
        notify('restarting',backup=str(backup))
        command([str(web),'start']);check_health(base,info['release']['tag'].lstrip('v'))
        command([str(watchdog),'start'])
        return 'complete'
    except Exception:
        if changed:
            notify('rolling_back',backup=str(backup))
            try:
                # The known-good init script can stop a failed replacement panel.
                command([str(backup/'router/opt/etc/init.d/S101awg3-web'),'stop'])
                for source,destination in FILES.items():
                    if digest(backup/source)!=records[source]['sha256']: raise UpdateError('backup_corrupt')
                    atomic_copy(backup/source,root/destination,records[source]['mode'])
                command([str(web),'start']);check_health(base,info['current'])
                command([str(watchdog),'start'])
            except Exception: raise UpdateError('rollback_failed') from None
            raise UpdateError('rolled_back') from None
        if watchdog_stopped:
            try: command([str(web),'start']);command([str(watchdog),'start'])
            except Exception: raise UpdateError('service_restart_failed') from None
        raise UpdateError('installation_not_started') from None

def run_job(job,base=BASE,runpath=RUN,root=Path('/'),fetch=download,command=run_command,check_health=health):
    job=Path(job);base=Path(base);runpath=Path(runpath);root=Path(root)
    lock=runpath/'update.lock';service_lock=runpath/'service.lock'
    state=base/'updates/state.json';service_owned=False
    def notify(phase,**extra):
        previous=read_json(state)
        atomic_json(state,dict(previous,phase=phase,updated=int(time.time()),**extra))
    try:
        (lock/'pid').write_text(str(os.getpid()))
        info=read_json(job/'job.json');release=info['release']
        if version(release['tag'])<=version(info['current']): raise UpdateError('no_new_version')
        prefix='https://github.com/'+REPO+'/releases/download/'+release['tag']+'/'
        if release['archive']!=prefix+ASSET or release['checksum']!=prefix+ASSET+'.sha256': raise UpdateError('untrusted_download_url')
        if shutil.disk_usage(job).free<MAX_DOWNLOAD+16*1024*1024: raise UpdateError('not_enough_storage')
        notify('downloading')
        fetch(release['checksum'],job/'checksum',1024)
        fetch(release['archive'],job/'package.tar.gz',MAX_DOWNLOAD)
        notify('verifying')
        verified_stage(job/'package.tar.gz',job/'checksum',job/'stage',release['tag'],root,release.get('digest'))
        try: service_lock.mkdir()
        except FileExistsError: raise UpdateError('vpn_service_busy') from None
        service_owned=True;(service_lock/'pid').write_text(str(os.getpid()))
        notify('preparing')
        phase=install_stage(job/'stage',job,base,root,notify,command,check_health)
        notify(phase,error=None)
    except Exception as exc:
        code=str(exc) if isinstance(exc,UpdateError) else 'update_failed'
        notify(code if code in ('rolled_back','rollback_failed') else 'failed',error=code)
    finally:
        if service_owned:
            (service_lock/'pid').unlink(missing_ok=True);service_lock.rmdir()
        # Only clean paths within this job; backups and the journal are retained.
        stage=job/'stage'
        if stage.exists() and not stage.is_symlink() and stage.resolve().parent==job.resolve(): shutil.rmtree(stage)
        for name in ('package.tar.gz','checksum'): (job/name).unlink(missing_ok=True)
        (lock/'pid').unlink(missing_ok=True);lock.rmdir()

def dead_worker(lock):
    if not lock.exists() or os.name!='posix': return False
    try:
        pid=int((lock/'pid').read_text())
        if pid<=1:return False
        os.kill(pid,0)
        # A finished, unreaped child also cannot own an update operation.
        stat=Path('/proc')/str(pid)/'stat'
        if stat.exists() and stat.read_text().rsplit(')',1)[1].strip().startswith('Z '):return True
    except ProcessLookupError:return True
    except (ValueError,OSError):return False
    return False

class Manager:
    def __init__(self,base=BASE,runpath=RUN,appdir=None,fetch=download,launch=subprocess.Popen):
        self.base,self.runpath=Path(base),Path(runpath)
        self.appdir=Path(appdir) if appdir else Path(__file__).parent
        self.fetch,self.launch=fetch,launch
        self.folder=self.base/'updates'
    def current(self):
        value=(self.appdir/'VERSION').read_text().strip();version(value);return value
    def status(self):
        cached=read_json(self.folder/'available.json')
        progress=read_json(self.folder/'state.json',{'phase':'idle'})
        lock=self.runpath/'update.lock'
        active=lock.exists() and not dead_worker(lock)
        if not active and progress.get('phase','idle') not in TERMINAL:
            progress=dict(progress,phase='interrupted',error='interrupted_manual_recovery')
        return {'current':self.current(),'latest':cached.get('tag'),
                'available':bool(cached.get('tag') and version(cached['tag'])>version(self.current())),
                'release_url':cached.get('url'),'active':active,'progress':progress}
    def check(self):
        if (self.runpath/'update.lock').exists(): raise UpdateError('update_busy')
        release=latest(self.fetch);atomic_json(self.folder/'available.json',release)
        return self.status()
    def start(self,tag):
        release=read_json(self.folder/'available.json')
        if not isinstance(tag,str) or tag!=release.get('tag'): raise UpdateError('check_update_first')
        if version(tag)<=version(self.current()): raise UpdateError('no_new_version')
        previous=read_json(self.folder/'state.json')
        if previous.get('phase') in ('installing','restarting','rolling_back','rollback_failed') and not self.status()['active']:
            raise UpdateError('interrupted_manual_recovery')
        self.runpath.mkdir(parents=True,exist_ok=True)
        lock=self.runpath/'update.lock'
        if dead_worker(lock):
            (lock/'pid').unlink(missing_ok=True);lock.rmdir()
        try:lock.mkdir()
        except FileExistsError:raise UpdateError('update_busy') from None
        job=None
        try:
            (lock/'pid').write_text(str(os.getpid()))
            if (self.runpath/'service.lock').exists():raise UpdateError('vpn_service_busy')
            self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            job=Path(tempfile.mkdtemp(prefix='job-',dir=self.folder))
            atomic_json(job/'job.json',{'current':self.current(),'release':release})
            shutil.copyfile(self.appdir/'updater.py',job/'worker.py')
            atomic_json(self.folder/'state.json',{'phase':'queued','target':tag,'job':str(job),'updated':int(time.time())})
            with (job/'worker.log').open('ab') as output:
                process=self.launch([sys.executable,str(job/'worker.py'),'--run'],stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True)
            try:(lock/'pid').write_text(str(process.pid))
            except FileNotFoundError:
                if read_json(self.folder/'state.json').get('phase') not in TERMINAL: raise
        except Exception:
            if job is not None: atomic_json(self.folder/'state.json',{'phase':'failed','error':'worker_start_failed','job':str(job)})
            (lock/'pid').unlink(missing_ok=True);lock.rmdir()
            raise
        return self.status()

if __name__=='__main__':
    os.umask(0o077)
    if sys.argv[1:]!=['--run']: raise SystemExit('Internal update worker; use the authenticated panel.')
    run_job(Path(__file__).resolve().parent)
