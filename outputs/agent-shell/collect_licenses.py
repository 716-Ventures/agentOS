#!/usr/bin/env python3
"""Collect locked Cargo dependency notices into the immutable runtime payload."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def collect(manifests,output):
    packages={}
    license_root=Path(__file__).parent/'licenses'
    overrides=json.loads((license_root/'overrides.json').read_text())
    for manifest in manifests:
        metadata=json.loads(subprocess.check_output(['cargo','metadata','--locked','--format-version=1','--filter-platform=aarch64-unknown-linux-gnu','--manifest-path',str(manifest)],text=True))
        nodes={n['id']:n for n in metadata['resolve']['nodes']};pending=[metadata['resolve']['root']];reachable=set()
        while pending:
            ident=pending.pop()
            if ident in reachable:continue
            reachable.add(ident);pending.extend(d['pkg'] for d in nodes[ident]['deps'])
        for package in metadata['packages']:
            if package['id'] in reachable and package.get('source'):packages[package['id']]=package
    if output.exists():
        marker=output/'dependencies.json'
        if output.is_symlink() or not marker.is_file() or json.loads(marker.read_text()).get('format')!=1:
            raise ValueError('Refusing to replace a directory that is not a generated dependency notice collection')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.licenses-',dir=output.parent) as directory:
        root=Path(directory);records=[]
        for package in sorted(packages.values(),key=lambda p:p['id']):
            source=Path(package['manifest_path']).parent
            candidates=set(p for pattern in ('LICENSE*','LICENCE*','COPYING*','COPYRIGHT*','NOTICE*') for p in source.glob(pattern) if p.is_file())
            if package.get('license_file'):
                path=source/package['license_file']
                if not path.is_file():raise ValueError('Missing dependency license: '+package['name'])
                candidates.add(path)
            override=None
            if not candidates:
                override=overrides.get(package['name']+'@'+package['version'])
                if override and override['license']==package.get('license'):
                    for notice in override['notices']:
                        path=license_root/notice['notice']
                        if hashlib.sha256(path.read_bytes()).hexdigest()!=notice['sha256']:raise ValueError('Pinned dependency notice changed')
                        candidates.add(path)
                else:raise ValueError('Dependency has no packaged license notice: '+package['name']+' '+package['version'])
            identity=package['name']+'-'+package['version']+'-'+hashlib.sha256(package['source'].encode()).hexdigest()[:12]
            notices=[]
            for path in sorted(candidates):
                data=path.read_bytes()
                if len(data)>1024*1024:raise ValueError('Oversized dependency notice: '+package['name'])
                digest=hashlib.sha256(data).hexdigest();name=identity+'/'+digest[:12]+'-'+path.name
                destination=root/name;destination.parent.mkdir(exist_ok=True);destination.write_bytes(data)
                notices.append({'path':name,'sha256':digest})
            records.append({'name':package['name'],'version':package['version'],'source':package['source'],'license':package.get('license'),'notices':notices,'supplemental_notice':override})
        (root/'dependencies.json').write_text(json.dumps({'format':1,'packages':records},indent=2,sort_keys=True)+'\n')
        if output.exists():shutil.rmtree(output)
        shutil.copytree(root,output)
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('manifests',type=Path,nargs='+');parser.add_argument('--output',type=Path,default=Path(__file__).parent/'third-party-licenses');args=parser.parse_args()
    records=collect(args.manifests,args.output);print('Collected dependency notices:',len(records))

if __name__=='__main__':main()
