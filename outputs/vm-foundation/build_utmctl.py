#!/usr/bin/env python3
"""Build a pinned UTM controller without its unconditional hidden-app launch flag."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT/'runtime/utmctl-control'
REVISION='048ca7498ea3a374439149d51739d94c5300bcda' # official UTM v4.7.5
ARGUMENT_PARSER='8f4d2753f0e4778c76d5f05ad16c74f707390531'
SOURCES={
    'utmctl/UTMCtl.swift':'007a1ef14182d73fda4d24e52511112fa9801a10ff56d3d067ec096ce759ffe6',
    'Scripting/UTMScripting.swift':'40b64b2e8997d310c8f2ee55a05c38440c0374fec60e57fff81b43507d68a0cd',
    'LICENSE':'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30',
}
POLICY='foreground-launch/1'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def controller(output=OUTPUT):
    output=Path(output)
    if not output.exists():return 'utmctl'
    binary=output/'utmctl';report=output/'build.json'
    if output.is_symlink() or binary.is_symlink() or report.is_symlink():
        raise RuntimeError('UTM control build must not be a symlink')
    value=json.loads(report.read_text())
    if (value.get('source_revision')!=REVISION or value.get('launch_policy')!=POLICY
            or not binary.is_file() or sha(binary)!=value.get('binary_sha256')):
        raise RuntimeError('UTM control build is incomplete or changed; inspect it before rebuilding')
    return str(binary)


def fetch(name):
    url='https://raw.githubusercontent.com/utmapp/UTM/'+REVISION+'/'+name
    with urllib.request.urlopen(url,timeout=30) as response:data=response.read(1024*1024+1)
    if len(data)>1024*1024 or hashlib.sha256(data).hexdigest()!=SOURCES[name]:
        raise ValueError('Pinned UTM source integrity failure: '+name)
    return data


def patch_launch(source):
    before='app.launchFlags = [.defaults, .andHide]'
    if source.count(before)!=1:raise ValueError('UTM launch patch no longer matches the pinned source')
    return source.replace(before,'app.launchFlags = [.defaults]')


def build(output=OUTPUT):
    output=Path(output).expanduser().resolve()
    if output.exists():
        print('Verified existing controller:',controller(output));return
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.utmctl-build-',dir=output.parent) as directory:
        work=Path(directory);source=work/'Sources/utmctl';source.mkdir(parents=True)
        for name in SOURCES:
            data=fetch(name)
            if name=='LICENSE':(work/'LICENSE-UTM').write_bytes(data)
            else:
                text=data.decode()
                if name=='utmctl/UTMCtl.swift':text=patch_launch(text)
                (source/Path(name).name).write_text(text)
        (work/'Package.swift').write_text('''// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "AgentOSUTMControl", platforms: [.macOS(.v12)], dependencies: [.package(url: "https://github.com/apple/swift-argument-parser", revision: "'''+ARGUMENT_PARSER+'''" )], targets: [.executableTarget(name: "utmctl", dependencies: [.product(name: "ArgumentParser", package: "swift-argument-parser")])])
''')
        env=dict(os.environ)
        xcode=Path('/Applications/Xcode.app/Contents/Developer')
        if 'DEVELOPER_DIR' not in env and xcode.exists():env['DEVELOPER_DIR']=str(xcode)
        subprocess.run(['swift','build','-c','release','--package-path',str(work)],env=env,check=True)
        result=work/'result';result.mkdir(mode=0o700)
        shutil.copy2(work/'.build/release/utmctl',result/'utmctl')
        shutil.copy2(work/'LICENSE-UTM',result/'LICENSE-UTM')
        shutil.copy2(work/'.build/checkouts/swift-argument-parser/LICENSE.txt',result/'LICENSE-ArgumentParser')
        report={'source_revision':REVISION,'source_sha256':SOURCES,'argument_parser_revision':ARGUMENT_PARSER,
                'launch_policy':POLICY,'binary_sha256':sha(result/'utmctl')}
        (result/'build.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
        # Publish a complete private build. Never replace a prior controller in use.
        os.rename(result,output)
    print('Built controller:',controller(output))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=OUTPUT)
    build(parser.parse_args().output)
