import importlib.util
import json
from pathlib import Path
import tempfile
import socket
import threading
import unittest
from unittest.mock import patch, Mock
root=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,root/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
install=load('install_runtime');bootstrap=load('bootstrap')

class Installation(unittest.TestCase):
    def fixture(self,tmp):
        base=Path(tmp);source=base/'source';source.mkdir()
        for name in ('target/release/agent-os-core','services/common.py','services/broker-launcher.sh',
                     'LICENSE','client/agent_os.py','systemd/agent-os-core.service','Cargo.toml','Cargo.lock','dependencies.json','release-contract.json','install_runtime.py'):
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True)
            if name=='release-contract.json':path.write_text(json.dumps({'format':1,'state_contract':'agentos.state/1','units':['agent-os-core'],'login_identity':1}))
            elif name.endswith('.py'):path.write_text('pass\n')
            elif name=='target/release/agent-os-core':path.write_bytes(b'\x7fELF\x02\x01'+b'\0'*12+(183).to_bytes(2,'little'))
            else:path.write_text('fixture '+name)
        instance=install.Installer(base/'system');instance.state.mkdir(parents=True)
        instance.reset_start_limits=Mock()
        instance.login_identity=Mock(return_value=type('Login',(),{'pw_uid':1000,'pw_shell':'/bin/bash'})())
        (instance.state/'dependencies.json').write_text('{}')
        (instance.state/'voice.json').write_text('{}')
        return instance,source

    def test_selected_login_is_retained_and_recycled_identity_is_rejected(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            instance=install.Installer(Path(tmp),login_user='alice')
            instance.path('/var/lib').mkdir(parents=True)
            with patch.object(install.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1001,pw_shell='/bin/bash')),patch.object(instance,'run') as run:
                instance.accounts()
                self.assertIn(['usermod','-a','-G','agentos,agentos-broker','alice'],[call.args[0] for call in run.call_args_list])
            restored=install.Installer(Path(tmp))
            self.assertEqual(restored.login_user,'alice')
            with patch.object(install.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1002,pw_shell='/bin/bash')):
                with self.assertRaisesRegex(ValueError,'UID changed'):restored.login_identity()
            with self.assertRaisesRegex(ValueError,'migration'):install.Installer(Path(tmp),login_user='bob')
            instance.login_config.chmod(0o666)
            with self.assertRaisesRegex(ValueError,'write access'):install.Installer(Path(tmp))

    def test_login_configuration_rejects_service_accounts_and_invalid_names(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('-root','root; echo bad','a'*33):
                with self.assertRaisesRegex(ValueError,'valid existing'):install.Installer(Path(tmp),login_user=name)
            instance=install.Installer(Path(tmp),login_user='alice')
            for uid,shell in [(0,'/bin/bash'),(999,'/bin/bash'),(1000,'/usr/sbin/nologin'),(1000,'/bin/false')]:
                with patch.object(install.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=uid,pw_shell=shell)):
                    with self.assertRaisesRegex(ValueError,'interactive'):instance.login_identity()
            instance.login_config.parent.mkdir(parents=True)
            instance.login_config.symlink_to(Path(tmp)/'missing')
            with self.assertRaisesRegex(ValueError,'regular file'):install.Installer(Path(tmp))

    def test_legacy_release_cannot_discard_the_selected_login_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);instance.login_user='alice'
            contract=json.loads((source/'release-contract.json').read_text());contract.pop('login_identity')
            (source/'release-contract.json').write_text(json.dumps(contract))
            ident=instance.stage(source)
            with patch.object(instance,'run') as run:
                with self.assertRaisesRegex(ValueError,'retain.*login identity'):instance.activate(ident)
                run.assert_not_called()
                self.assertFalse(instance.journal.exists())

    def test_interrupted_first_install_retains_login_before_account_setup(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            instance=install.Installer(Path(tmp),login_user='alice');instance.state.mkdir(parents=True)
            instance.record({'release':'fixture','phase':'staged','login_user':'alice','login_uid':1001})
            recovered=install.Installer(Path(tmp))
            self.assertEqual(recovered.login_user,'alice')
            with patch.object(install.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1002,pw_shell='/bin/bash')):
                with self.assertRaisesRegex(ValueError,'UID changed'):recovered.login_identity()
            with self.assertRaisesRegex(ValueError,'migration'):install.Installer(Path(tmp),login_user='bob')

    def test_counter_reset_skips_new_units_and_only_touches_loaded_release_units(self):
        instance=install.Installer();instance.active_units=['agent-os-core','agent-os-broker']
        for rows,expected in [([],None),([{'unit':'agent-os-core.service'},{'unit':'unrelated.service'}],['systemctl','reset-failed','agent-os-core'])]:
            with self.subTest(rows=rows),patch.object(instance,'run',return_value=Mock(stdout=json.dumps(rows))) as run:
                instance.reset_start_limits()
                self.assertEqual(run.call_args_list[0].args[0],['systemctl','list-units','--all','--plain','--output=json','agent-os-core.service','agent-os-broker.service'])
                self.assertEqual(run.call_count,1 if expected is None else 2)
                if expected:self.assertEqual(run.call_args.args[0],expected)

    def test_runtime_health_uses_a_bounded_database_read_instead_of_complete_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);instance.active_units=['agent-os-core']
            path=instance.path('/run/agent-os/runtime.sock');path.parent.mkdir(parents=True)
            listener=socket.socket(socket.AF_UNIX);listener.bind(str(path));listener.listen(1);listener.settimeout(3)
            observed=[]
            def serve():
                with listener.accept()[0] as conn:
                    observed.append(json.loads(conn.makefile('rb').readline()))
                    conn.sendall(b'{"ok":true,"result":{"revision":12,"rows":[]}}\n')
            thread=threading.Thread(target=serve);thread.start()
            try:
                with patch.object(install.subprocess,'run',return_value=type('Result',(),{'stdout':'active\n'})()):instance.health()
            finally:thread.join(timeout=3);listener.close()
            self.assertFalse(thread.is_alive());self.assertEqual(observed,[{'op':'state.page','collection':'activities','limit':1}])
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

    def saved_component(self,instance,kind):
        import sqlite3
        path=instance.path('/var/lib/agent-os-runtime/state.sqlite3');path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS presentation_documents(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
            db.execute('INSERT OR REPLACE INTO presentation_documents VALUES (?,?)',('surface',json.dumps({'elements':{'item':{'type':kind}}})))

    def test_rollback_refuses_new_components_without_stopping_the_live_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);first=instance.stage(source);self.activate_fixture(instance,first)
            contract=json.loads((source/'release-contract.json').read_text());contract['components']=['Text@1','Image@1']
            (source/'release-contract.json').write_text(json.dumps(contract));second=instance.stage(source);self.activate_fixture(instance,second)
            self.saved_component(instance,'Image@1');before=instance.journal.read_bytes()
            with patch.object(instance,'run') as run:
                with self.assertRaisesRegex(ValueError,'Image@1'):instance.rollback(first)
            run.assert_not_called();self.assertEqual(instance.journal.read_bytes(),before)
            self.assertEqual((instance.root/'current').resolve().name,second)
            self.saved_component(instance,'Text@1')
            with patch.object(instance,'accounts'),patch.object(instance,'run'),patch.object(instance,'health'):instance.rollback(first)
            self.assertEqual((instance.root/'current').resolve().name,first)

    def test_component_saved_during_preflight_restores_old_services_and_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);first=instance.stage(source);self.activate_fixture(instance,first)
            contract=json.loads((source/'release-contract.json').read_text());contract['components']=['Text@1']
            (source/'release-contract.json').write_text(json.dumps(contract));second=instance.stage(source)
            self.saved_component(instance,'Text@1');before=instance.journal.read_bytes();calls=[]
            def run(args):
                calls.append(args)
                if args[:2]==['systemctl','stop']:self.saved_component(instance,'Image@1')
            with patch.object(instance,'accounts'),patch.object(instance,'run',side_effect=run),patch.object(instance,'health'):
                with self.assertRaisesRegex(ValueError,'Image@1'):instance.activate(second)
            self.assertIn(['systemctl','start','agent-os-core'],calls)
            self.assertEqual(instance.journal.read_bytes(),before)
            self.assertEqual((instance.root/'current').resolve().name,first)

    def test_component_contract_rejects_duplicates_and_malformed_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp)
            for components in (['Text@1','Text@1'],['Text'],['Text@0'],[],'Text@1'):
                contract=json.loads((source/'release-contract.json').read_text());contract['components']=components
                (source/'release-contract.json').write_text(json.dumps(contract));ident=instance.stage(source)
                with self.assertRaisesRegex(ValueError,'component'):instance.contract(instance.root/'releases'/ident)

    def test_interrupted_activation_preserves_original_previous_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);first=instance.stage(source);self.activate_fixture(instance,first)
            (source/'services/common.py').write_text('value=3\n');second=instance.stage(source)
            instance.record({'release':second,'previous':str(instance.root/'releases'/first),'phase':'activated'})
            instance.link(instance.root/'current',instance.root/'releases'/second)
            self.activate_fixture(instance,second)
            self.assertEqual(Path(json.loads(instance.journal.read_text())['previous']).name,first)

    def desktop_fixture(self,tmp):
        instance,source=self.fixture(tmp)
        contract=json.loads((source/'release-contract.json').read_text());contract['desktop']={'format':1};(source/'release-contract.json').write_text(json.dumps(contract))
        for crate,binary in [('native-shell','agent-os-desktop'),('native-compositor','agent-os-compositor')]:
            tree=source/crate;(tree/'target/release').mkdir(parents=True);(tree/'target/release'/binary).write_bytes((source/'target/release/agent-os-core').read_bytes())
            for name in ('Cargo.toml','Cargo.lock'):(tree/name).write_text(name)
        (source/'services/desktop_session.py').write_text('pass\n');(source/'services/session-launcher.sh').write_text('#!/bin/sh\nexit 0\n')
        (source/'session').mkdir();(source/'session/agent-os.desktop').write_text('[Desktop Entry]\nName=agentOS\n')
        licenses=source/'third-party-licenses';licenses.mkdir();(licenses/'dependencies.json').write_text('{"format":1,"packages":[]}')
        return instance,source

    def test_graphical_artifacts_are_integrity_checked_and_bound_to_the_release(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.desktop_fixture(tmp);ident=instance.stage(source);release=instance.root/'releases'/ident
            self.assertEqual(((release/'native/agent-os-desktop').resolve()).stat().st_mode & 0o777,0o755)
            self.assertTrue(instance.contract(release)['desktop'])
            with patch.object(install.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1000,pw_shell='/bin/bash')):self.activate_fixture(instance,ident)
            self.assertEqual(instance.path('/usr/local/bin/agent-os-desktop').resolve(),(release/'native/agent-os-desktop').resolve())
            self.assertIn('AGENT_OS_COMPOSITOR_UID=1000',instance.path('/etc/systemd/system/agent-os-core.service.d/30-compositor.conf').read_text())
            ((release/'native/agent-os-desktop').resolve()).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'integrity'):instance.verify(release)

    def test_graphical_rollback_removes_only_its_desktop_bindings_and_preserves_user_state(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            instance,source=self.fixture(tmp);terminal=instance.stage(source);self.activate_fixture(instance,terminal)
            contract=json.loads((source/'release-contract.json').read_text());contract['desktop']={'format':1};(source/'release-contract.json').write_text(json.dumps(contract))
            for crate,binary in [('native-shell','agent-os-desktop'),('native-compositor','agent-os-compositor')]:
                tree=source/crate;(tree/'target/release').mkdir(parents=True);(tree/'target/release'/binary).write_bytes((source/'target/release/agent-os-core').read_bytes())
                for name in ('Cargo.toml','Cargo.lock'):(tree/name).write_text(name)
            (source/'services/desktop_session.py').write_text('pass\n');(source/'services/session-launcher.sh').write_text('#!/bin/sh\nexit 0\n');(source/'session').mkdir();(source/'session/agent-os.desktop').write_text('fixture');(source/'third-party-licenses').mkdir();(source/'third-party-licenses/dependencies.json').write_text('{"format":1,"packages":[]}')
            graphical=instance.stage(source)
            with patch.object(install.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1000,pw_shell='/bin/bash')):self.activate_fixture(instance,graphical)
            user=instance.path('/home/developer/.local/state/agent-os/native-drafts.json');user.parent.mkdir(parents=True);user.write_text('retain my draft')
            with patch.object(instance,'accounts'),patch.object(instance,'run'),patch.object(instance,'health'):instance.rollback(terminal)
            self.assertFalse(instance.path('/usr/local/bin/agent-os-desktop').exists());self.assertFalse(instance.path('/usr/share/wayland-sessions/agent-os.desktop').exists());self.assertEqual(user.read_text(),'retain my draft')
