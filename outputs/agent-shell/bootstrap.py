#!/usr/bin/python3
"""Install development/verification dependencies from authenticated Debian snapshots."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent
STATE=Path('/var/lib/agent-os-install')


def sources(profile):
    if not re.fullmatch(r'\d{8}T\d{6}Z',profile['snapshot']):raise ValueError('Invalid snapshot')
    entries=[]
    for archive in profile['archives']:
        if archive['name'] not in ('debian','debian-security'):raise ValueError('Invalid archive')
        if any(s not in ('trixie','trixie-updates','trixie-security') for s in archive['suites']):raise ValueError('Invalid suite')
        entries.append('Types: deb\nURIs: https://snapshot.debian.org/archive/'+archive['name']+'/'+profile['snapshot']+
                       '/\nSuites: '+' '.join(archive['suites'])+'\nComponents: main\n'+
                       'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\nCheck-Valid-Until: no\n')
    return '\n'.join(entries)


def manifest(profile_hash):
    rows=subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'],text=True)
    return {'profile_sha256':profile_hash,'packages':dict((name,version) for name,version,status in
            (row.split('\t') for row in rows.splitlines()) if status=='installed')}


def main():
    if os.geteuid()!=0:raise SystemExit('Run bootstrap.py with sudo')
    os_release=Path('/etc/os-release').read_text()
    if 'VERSION_ID="13"' not in os_release or subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()!='arm64':
        raise SystemExit('This dependency recipe requires Debian 13 arm64')
    raw=(ROOT/'dependencies.json').read_bytes();profile=json.loads(raw)
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*',p) for p in profile['packages']):raise ValueError('Invalid package')
    profile_hash=hashlib.sha256(raw).hexdigest()
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True);STATE.chmod(0o700)
    report=STATE/'dependencies.json'
    if report.exists() and json.loads(report.read_text())==manifest(profile_hash):
        print('Dependency profile and installed versions unchanged.');return
    # Isolated lists/sources keep the guest's normal security-update configuration intact.
    with tempfile.TemporaryDirectory(prefix='agent-os-apt-') as tmp:
        root=Path(tmp);root.chmod(0o755)
        source=root/'snapshot.sources';source.write_text(sources(profile))
        lists=root/'lists';lists.mkdir(mode=0o755)
        options=['-o','Dir::Etc::sourcelist='+str(source),'-o','Dir::Etc::sourceparts=-',
                 '-o','Dir::State::lists='+str(lists),'-o','Acquire::Retries=3']
        env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'}
        subprocess.run(['apt-get',*options,'update'],env=env,check=True)
        subprocess.run(['apt-get',*options,'install','-y','--no-install-recommends',*profile['packages']],env=env,check=True)
    result=manifest(profile_hash)
    missing=set(profile['packages'])-{name.split(':')[0] for name in result['packages']}
    if missing:raise RuntimeError('Missing dependencies: '+', '.join(sorted(missing)))
    tmp=report.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');tmp.replace(report)
    print('Installed locked-snapshot dependency profile; versions recorded in',report)

if __name__=='__main__':main()
