import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,root/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
install=load('install_runtime');bootstrap=load('bootstrap')

class Installation(unittest.TestCase):
    def fixture(self,tmp):
        base=Path(tmp);source=base/'source';source.mkdir()
        for name in ('target/release/agent-os-core','services/common.py','services/broker-launcher.sh',
                     'client/agent_os.py','systemd/agent-os-core.service','Cargo.toml','Cargo.lock','dependencies.json','release-contract.json','install_runtime.py'):
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True)
            if name=='release-contract.json':path.write_text(json.dumps({'format':1,'state_contract':'agentos.state/1','units':['agent-os-core']}))
            elif name.endswith('.py'):path.write_text('pass\n')
            elif name=='target/release/agent-os-core':path.write_bytes(b'\x7fELF\x02\x01'+b'\0'*12+(183).to_bytes(2,'little'))
            else:path.write_text('fixture '+name)
        instance=install.Installer(base/'system');instance.state.mkdir(parents=True)
        (instance.state/'dependencies.json').write_text('{}')
        (instance.state/'voice.json').write_text('{}')
        return instance,source

    def test_staging_is_content_addressed_and_does_not_touch_live_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp)
            current=instance.root/'current'
            first=instance.stage(source)
            self.assertFalse(current.exists());self.assertFalse(instance.journal.exists())
            self.assertEqual(instance.stage(source),first)
            (source/'services/common.py').write_text('value=1\n')
            self.assertNotEqual(instance.stage(source),first)
            old=instance.root/'releases'/first
            self.assertEqual((old/'services/common.py').read_text(),'pass\n')

    def test_corrupt_release_is_refused_before_stopping_any_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);ident=instance.stage(source)
            (instance.root/'releases'/ident/'agent-os-core').write_text('corrupt')
            with patch.object(instance,'run') as run:
                with self.assertRaisesRegex(ValueError,'integrity'):instance.activate(ident)
            run.assert_not_called();self.assertFalse(instance.journal.exists())

    def test_recovery_uses_durable_staged_release_not_the_working_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);ident=instance.stage(source)
            instance.record({'release':ident,'phase':'stopped'})
            with patch.object(instance,'activate') as activate:instance.recover()
            activate.assert_called_once_with(ident)
            self.assertEqual(json.loads(instance.journal.read_text())['release'],ident)
            self.assertEqual(instance.journal.stat().st_mode & 0o777,0o600)

    def test_snapshot_sources_keep_archive_authentication_and_bound_scope(self):
        profile=json.loads((root/'dependencies.json').read_text());text=bootstrap.sources(profile)
        self.assertIn('Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg',text)
        self.assertNotIn('Trusted:',text)
        self.assertIn(profile['snapshot'],text)
        for bad in ('../private','2026;command'):
            with self.assertRaises(ValueError):bootstrap.sources({**profile,'snapshot':bad})

    def test_invalid_source_or_host_binary_never_replaces_a_live_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp)
            (source/'services/common.py').write_text('invalid python ??')
            with self.assertRaises(SyntaxError):instance.stage(source)
            self.assertFalse(instance.journal.exists())
            (source/'services/common.py').write_text('pass')
            (source/'target/release/agent-os-core').write_bytes(b'host executable')
            with self.assertRaisesRegex(ValueError,'ARM64 Linux'):instance.stage(source)
            self.assertFalse(instance.journal.exists())

    def activate_fixture(self,instance,ident):
        metadata=instance.path('/etc/agent-os/release.json');metadata.parent.mkdir(parents=True,exist_ok=True);metadata.write_text('{}')
        with patch.object(instance,'accounts'),patch.object(instance,'run'),patch.object(instance,'health'):
            instance.activate(ident)

    def test_rollback_preserves_state_and_repeated_install_preserves_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);first=instance.stage(source);self.activate_fixture(instance,first)
            state=instance.path('/var/lib/agent-os/user-state');state.mkdir(parents=True);(state/'draft').write_text('Uncommitted λ')
            (source/'services/common.py').write_text('value=2\n');second=instance.stage(source)
            self.activate_fixture(instance,second);self.activate_fixture(instance,second)
            receipt=json.loads((instance.state/'installed.json').read_text());self.assertEqual(Path(receipt['previous']).name,first)
            with patch.object(instance,'accounts'),patch.object(instance,'run'),patch.object(instance,'health'):instance.rollback()
            self.assertEqual((instance.root/'current').resolve().name,first);self.assertEqual((state/'draft').read_text(),'Uncommitted λ')
            self.assertEqual(json.loads((instance.state/'installed.json').read_text())['phase'],'complete')

    def test_incompatible_release_refused_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);first=instance.stage(source);self.activate_fixture(instance,first)
            contract=json.loads((source/'release-contract.json').read_text());contract['state_contract']='agentos.state/2';(source/'release-contract.json').write_text(json.dumps(contract));second=instance.stage(source)
            before=instance.journal.read_bytes()
            with patch.object(instance,'run') as run:
                with self.assertRaisesRegex(ValueError,'migration'):instance.activate(second)
                with self.assertRaisesRegex(ValueError,'incompatible'):instance.rollback(second)
            run.assert_not_called();self.assertEqual(instance.journal.read_bytes(),before);self.assertEqual((instance.root/'current').resolve().name,first)

    def test_interrupted_activation_preserves_original_previous_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);first=instance.stage(source);self.activate_fixture(instance,first)
            (source/'services/common.py').write_text('value=3\n');second=instance.stage(source)
            instance.record({'release':second,'previous':str(instance.root/'releases'/first),'phase':'activated'})
            instance.link(instance.root/'current',instance.root/'releases'/second)
            self.activate_fixture(instance,second)
            self.assertEqual(Path(json.loads(instance.journal.read_text())['previous']).name,first)
