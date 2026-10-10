import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import installation_test

spec=importlib.util.spec_from_file_location('release_bundle',Path(__file__).resolve().parents[1]/'services/release_bundle.py')
bundle=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundle)
openssl='/opt/homebrew/opt/openssl@3/bin/openssl' if Path('/opt/homebrew/opt/openssl@3/bin/openssl').exists() else '/usr/bin/openssl'

class SignedBundles(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.patcher=patch.object(bundle,'OPENSSL',openssl);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.installer,self.source=installation_test.Installation().fixture(self.base)
        profile=b'{"packages":["python3"]}'
        (self.source/'dependencies.json').write_bytes(profile)
        (self.installer.state/'dependencies.json').write_text(json.dumps({'profile_sha256':bundle.sha(profile),'packages':{'python3':'3.13'}}))
        self.ident=self.installer.stage(self.source)
        self.key=self.base/'private.pem';self.public=self.base/'public.pem'
        subprocess.run([openssl,'genpkey','-algorithm','Ed25519','-out',str(self.key)],check=True,capture_output=True)
        subprocess.run([openssl,'pkey','-in',str(self.key),'-pubout','-out',str(self.public)],check=True,capture_output=True)
        self.archive=self.base/'runtime.tar.gz'
        bundle.export(self.installer,self.ident,self.key,self.archive)
        self.destination=type(self.installer)(self.base/'destination');self.destination.state.mkdir(parents=True)
        (self.destination.state/'voice.json').write_text('{}')

    def load(self,path=None):
        with patch.object(bundle.platform,'system',return_value='Linux'),patch.object(bundle.platform,'machine',return_value='aarch64'),patch.object(bundle,'installed_packages',return_value={'python3':'3.13'}):
            return bundle.import_bundle(self.destination,path or self.archive,self.public)

    def mutate(self,change):
        with tarfile.open(self.archive,'r:gz') as source:items=[(info,source.extractfile(info).read()) for info in source]
        items=change(items)
        changed=self.base/'changed.tar.gz'
        with tarfile.open(changed,'w:gz') as target:
            for info,data in items:
                info.size=len(data);target.addfile(info,io.BytesIO(data))
        return changed

    def assert_rejected(self,path):
        with self.assertRaises((ValueError,OSError)):self.load(path)
        self.assertFalse((self.destination.root/'current').exists())
        self.assertFalse(self.destination.journal.exists())
        self.assertEqual(list((self.destination.root/'releases').glob('*')),[])

    def test_https_fetch_verifies_and_stages_without_activation(self):
        response=io.BytesIO(self.archive.read_bytes());response.headers={}
        with patch.object(bundle.urllib.request,'build_opener') as opener, \
                patch.object(bundle.platform,'system',return_value='Linux'), \
                patch.object(bundle.platform,'machine',return_value='aarch64'), \
                patch.object(bundle,'installed_packages',return_value={'python3':'3.13'}):
            opener.return_value.open.return_value=response
            self.assertEqual(bundle.fetch_bundle(self.destination,'https://releases.example/runtime.tar.gz',self.public),self.ident)
        self.assertFalse((self.destination.root/'current').exists())
        self.assertFalse(self.destination.journal.exists())
        self.assertEqual(list(self.destination.state.glob('.download-*')),[])

    def test_fetch_rejects_transport_downgrade_url_credentials_and_oversized_body(self):
        for url in ('http://example.com/a','file:///tmp/a','https://user:secret@example.com/a','https://example.com/a#fragment','https://example.com/\n'):
            with self.subTest(url=url),self.assertRaises(ValueError):bundle.download_url(url)
        request=bundle.urllib.request.Request('https://example.com/a')
        with self.assertRaises(ValueError):bundle.SecureRedirect().redirect_request(request,None,302,'redirect',{},'http://example.com/a')
        response=io.BytesIO(b'123456789');response.headers={}
        with patch.object(bundle,'MAX_DOWNLOAD',8),patch.object(bundle.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            with self.assertRaisesRegex(ValueError,'size limit'):bundle.fetch_bundle(self.destination,'https://example.com/a',self.public)
        self.assertEqual(list(self.destination.state.glob('.download-*')),[])
        self.assertFalse((self.destination.root/'current').exists())

    def test_roundtrip_deterministic_only_manifest_payload_and_no_activation(self):
        release=self.installer.root/'releases'/self.ident
        (release/'unlisted-private-key').write_text('never export')
        second=self.base/'second.tar.gz';bundle.export(self.installer,self.ident,self.key,second)
        self.assertEqual(second.read_bytes(),self.archive.read_bytes())
        with tarfile.open(self.archive,'r:gz') as source:
            names=source.getnames();self.assertNotIn('release/unlisted-private-key',names)
            self.assertEqual(set(names[3:]),{'release/'+name for name in self.installer.verify(release)})
        self.assertEqual(self.load(),self.ident);self.assertEqual(self.load(),self.ident)
        staged=self.destination.root/'releases'/self.ident
        self.assertEqual(self.destination.verify(staged),self.installer.verify(release))
        self.assertEqual((staged/'agent-os-core').stat().st_mode & 0o777,0o755)
        self.assertFalse(self.destination.journal.exists());self.assertFalse((self.destination.root/'current').exists())

    def test_signature_and_signed_manifest_tampering(self):
        for index in (0,1,2,3):
            def alter(items):
                info,data=items[index];items[index]=(info,bytes([data[0]^1])+data[1:]);return items
            self.assert_rejected(self.mutate(alter))

    def test_duplicate_traversal_links_and_missing_payload(self):
        for kind in ('duplicate','traversal','symlink','missing','extra'):
            def alter(items):
                if kind=='duplicate':return items+[items[-1]]
                if kind=='missing':return items[:-1]
                info=tarfile.TarInfo('release/../escaped' if kind=='traversal' else 'release/extra')
                if kind=='symlink':info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd'
                return items+[(info,b'x')]
            self.assert_rejected(self.mutate(alter))
        self.assertFalse((self.destination.root/'escaped').exists())

    def test_wrong_trust_anchor_and_overwrite_refused(self):
        other=self.base/'other.pem';subprocess.run([openssl,'genpkey','-algorithm','Ed25519','-out',str(other)],check=True,capture_output=True)
        subprocess.run([openssl,'pkey','-in',str(other),'-pubout','-out',str(self.public)],check=True,capture_output=True)
        self.assert_rejected(self.archive)
        before=self.archive.read_bytes()
        with self.assertRaises(ValueError):bundle.export(self.installer,self.ident,self.key,self.archive)
        self.assertEqual(before,self.archive.read_bytes())

    def test_dependency_voice_and_architecture_mismatches_preserve_state(self):
        with patch.object(bundle.platform,'system',return_value='Linux'),patch.object(bundle.platform,'machine',return_value='aarch64'),patch.object(bundle,'installed_packages',return_value={'python3':'wrong'}):
            with self.assertRaisesRegex(ValueError,'dependency'):bundle.import_bundle(self.destination,self.archive,self.public)
        (self.destination.state/'voice.json').write_text('{"different":true}')
        with self.assertRaisesRegex(ValueError,'voice assets'):self.load()
        self.assertEqual((self.destination.state/'voice.json').read_text(),'{"different":true}')
        with patch.object(bundle.platform,'system',return_value='Darwin'):
            with self.assertRaisesRegex(ValueError,'ARM64 Linux'):bundle.validate_host(self.destination,self.installer.root/'releases'/self.ident)
        self.assertFalse(self.destination.journal.exists())

    def test_incompatible_state_contract_never_stages_or_changes_current(self):
        self.load();self.destination.link(self.destination.root/'current',self.destination.root/'releases'/self.ident)
        contract=json.loads((self.source/'release-contract.json').read_text());contract['state_contract']='agentos.state/2'
        (self.source/'release-contract.json').write_text(json.dumps(contract));different=self.installer.stage(self.source)
        changed=self.base/'incompatible.tar.gz';bundle.export(self.installer,different,self.key,changed)
        with self.assertRaisesRegex(ValueError,'migration'):self.load(changed)
        self.assertEqual((self.destination.root/'current').resolve().name,self.ident)
        self.assertFalse((self.destination.root/'releases'/different).exists())

    def test_size_limits_before_extraction(self):
        with patch.object(bundle,'MAX_FILE',1):self.assert_rejected(self.archive)
        with patch.object(bundle,'MAX_TOTAL',1):
            with self.assertRaisesRegex(ValueError,'size limit'):self.load()

if __name__=='__main__':unittest.main()
