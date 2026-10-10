#!/usr/bin/env python3
"""Stage real ARM64 graphical ELFs and pinned dependency notices without activation."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,file);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
installer=module('runtime_installer',ROOT/'install_runtime.py')
licenses=module('runtime_licenses',ROOT/'collect_licenses.py')
bundles=module('runtime_bundles',ROOT/'services/release_bundle.py')
with tempfile.TemporaryDirectory(prefix='agentos-graphical-release-') as directory:
    root=Path(directory);source=root/'source'
    shutil.copytree(ROOT,source,ignore=shutil.ignore_patterns('target','__pycache__','third-party-licenses','test-output'))
    (source/'target/release').mkdir(parents=True)
    shutil.copy2(ROOT/'target/release/agent-os-core',source/'target/release/agent-os-core')
    for crate,binary in [('native-shell','agent-os-desktop'),('native-compositor','agent-os-compositor')]:
        upstream=ROOT.parent/crate;tree=source/crate;tree.mkdir()
        for name in ('Cargo.toml','Cargo.lock','LICENSE-SMITHAY','THIRD_PARTY.md'):
            if (upstream/name).is_file():shutil.copy2(upstream/name,tree/name)
        if (upstream/'licenses').is_dir():shutil.copytree(upstream/'licenses',tree/'licenses')
        (tree/'target/release').mkdir(parents=True)
        # CI debug builds are still real ARM64 ELF programs. This checks packaging;
        # install.sh builds optimized programs for the actual guest release.
        shutil.copy2(upstream/'target/debug'/binary,tree/'target/release'/binary)
    records=licenses.collect([ROOT/'Cargo.toml',ROOT.parent/'native-shell/Cargo.toml',ROOT.parent/'native-compositor/Cargo.toml'],source/'third-party-licenses')
    assert records and all(record['notices'] for record in records)
    inst=installer.Installer(root/'prefix');inst.state.mkdir(parents=True)
    # This packaging fixture uses the CI host's actual dependency versions.
    # It does not claim Ubuntu CI qualifies the Debian guest dependency profile.
    profile=b'{"packages":["python3","openssl"]}\n'
    (source/'dependencies.json').write_bytes(profile)
    (inst.state/'dependencies.json').write_text(json.dumps({'profile_sha256':bundles.sha(profile),'packages':bundles.installed_packages()}))
    (inst.state/'voice.json').write_text('{}\n')
    ident=inst.stage(source);release=inst.root/'releases'/ident
    assert inst.contract(release)['desktop']=={'format':1}
    hashes=inst.verify(release)
    assert 'native/agent-os-desktop' in hashes and 'native/agent-os-compositor' in hashes
    for record in records:
        for notice in record['notices']:assert 'third-party-licenses/'+notice['path'] in hashes
    # Every file included in the release is covered, including dependency notices.
    assert set(hashes)=={str(p.relative_to(release)) for p in release.rglob('*') if p.is_file() and p.name!='manifest.json'}
    print(f'PASS: real ARM64 graphical release {ident}, {len(records)} dependencies with notices, complete integrity manifest')

    private=root/'ephemeral-private.pem';public=root/'ephemeral-public.pem'
    subprocess.run(['/usr/bin/openssl','genpkey','-algorithm','Ed25519','-out',str(private)],check=True,capture_output=True)
    subprocess.run(['/usr/bin/openssl','pkey','-in',str(private),'-pubout','-out',str(public)],check=True,capture_output=True)
    archive=root/'runtime.tar.gz';bundles.export(inst,ident,private,archive)
    destination=installer.Installer(root/'imported-prefix');destination.state.mkdir(parents=True)
    (destination.state/'voice.json').write_text('{}\n')
    assert bundles.import_bundle(destination,archive,public)==ident
    assert destination.verify(destination.root/'releases'/ident)==hashes
    assert not (destination.root/'current').exists() and not destination.journal.exists()
    print('PASS: signed real ARM64 graphical bundle verifies and stages without activation or user state')
