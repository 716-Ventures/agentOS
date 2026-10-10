import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


image = module('release_image', ROOT / 'build_release_image.py')
first = module('first_run', ROOT / 'guest/first-run.py')
package = module('image_package', ROOT / 'package_release_image.py')


class ReleaseImageTest(unittest.TestCase):
    def test_completed_image_publication_reuses_inode_and_survives_build_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'completed.qcow2'; output = root / 'image.qcow2'
            source.write_bytes(b'completed-image')
            image.publish_image(source, output)
            self.assertEqual(source.stat().st_ino, output.stat().st_ino)
            self.assertEqual(output.stat().st_mode & 0o777, 0o644)
            source.unlink()
            self.assertEqual(output.read_bytes(), b'completed-image')

    def test_publication_cannot_replace_existing_disk_or_follow_output_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'completed'; disk = root / 'existing'
            source.write_bytes(b'new'); disk.write_bytes(b'keep-existing')
            for target in (disk, root / 'symlink', root / 'dangling'):
                if target.name == 'symlink': target.symlink_to(disk)
                if target.name == 'dangling': target.symlink_to(root / 'absent')
                with self.subTest(target=target.name), self.assertRaises(FileExistsError):
                    image.publish_image(source, target)
            self.assertEqual(disk.read_bytes(), b'keep-existing')
            self.assertFalse((root / 'absent').exists())

    def test_personal_login_names_cannot_be_options_system_accounts_or_paths(self):
        self.assertEqual(first.username('chris'), 'chris')
        for value in ('root', 'debian', '-f', '../chris', 'Chris', '', 'a' * 32, 'a\nb', None):
            with self.subTest(value=value), self.assertRaises(ValueError): first.username(value)

    def test_image_runtime_identity_and_payload_changes_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = b'{"desktop":true}'
            hashes = {'release-contract.json': hashlib.sha256(contract).hexdigest()}
            ident = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
            release = root / ident; release.mkdir()
            (release / 'manifest.json').write_text(json.dumps(hashes))
            (release / 'release-contract.json').write_bytes(contract)
            self.assertEqual(image.payload(release), (ident, hashes))
            (release / 'release-contract.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'): image.payload(release)

    def test_traversal_symlinks_and_nonfiles_cannot_be_image_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / ('a' * 64); release.mkdir()
            (root / 'secret').write_text('not an image input')
            for name in ('../secret', '/secret', 'a//b', 'a/./b', 'a\\b'):
                (release / 'manifest.json').write_text(json.dumps({name: 'b' * 64}))
                with self.subTest(name=name), self.assertRaises(ValueError): image.payload(release)
            link = release / 'linked'; link.symlink_to(root / 'secret')
            with self.assertRaises(ValueError): image.regular(link)
            with self.assertRaises(ValueError): image.regular(root)

    def test_first_run_resumes_failed_activation_without_resetting_password(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory); accounts = {}; passwords = []; attempts = []
            def run(*args, **kwargs):
                if args[0] == 'useradd':
                    accounts[args[-1]] = SimpleNamespace(pw_uid=1000, pw_gecos=args[args.index('--comment')+1])
                elif args[0] == 'chpasswd': passwords.append(kwargs['input'])
                elif '--activate' in args:
                    attempts.append(args)
                    if len(attempts) == 1: raise subprocess.CalledProcessError(1, args)
            with patch.object(first, 'STATE', state), patch.object(first, 'account', side_effect=lambda name: accounts.get(name)), \
                    patch.object(first.pwd, 'getpwnam', side_effect=lambda name: accounts[name]), \
                    patch.object(first, 'run', side_effect=run), patch('builtins.input', return_value='chris'), \
                    patch.object(first.getpass, 'getpass', return_value='fixture-password-only') as password, \
                    patch.object(first, 'load', side_effect=lambda path: json.loads(path.read_text())):
                with self.assertRaises(subprocess.CalledProcessError): first.setup({'runtime_release': 'a'*64})
                self.assertFalse((state / 'ready').exists())
                self.assertTrue((state / 'account-ready').exists())
                self.assertEqual(json.loads((state / 'setup.json').read_text())['phase'], 'account-ready')
                first.setup({'runtime_release': 'a'*64})
                self.assertEqual(password.call_count, 2)
                self.assertEqual(len(passwords), 1)
                self.assertEqual(len(attempts), 2)
                self.assertNotIn('fixture-password-only', (state / 'setup.json').read_text())
                self.assertEqual(json.loads((state / 'ready').read_text())['uid'], 1000)
                accounts['chris'].pw_uid = 1001
                with self.assertRaisesRegex(ValueError, 'identity changed'): first.setup({'runtime_release': 'a'*64})

    def test_signed_bundle_has_no_seed_or_host_forward_and_detects_disk_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); key = root / 'private.pem'; public = root / 'public.pem'
            package.crypto('genpkey', '-algorithm', 'ED25519', '-out', key)
            public.write_bytes(package.crypto('pkey', '-in', key, '-pubout'))
            disk = root / 'image.qcow2'; disk.write_bytes(b'fixture disk')
            metadata = root / 'image.json'
            metadata.write_text(json.dumps({'format': 1, 'architecture': 'arm64',
                'image_sha256': package.digest(disk), 'update_key_sha256': package.digest(public)}))
            bundle = root / 'release.utm'; package.package(disk, metadata, key, bundle)
            package.verify(bundle, public)
            import plistlib
            config = plistlib.loads((bundle / 'config.plist').read_bytes())
            self.assertEqual([drive['ImageName'] for drive in config['Drive']], ['disk.qcow2'])
            self.assertEqual(config['Network'][0]['PortForward'], [])
            self.assertFalse((bundle / 'INCOMPLETE').exists())
            self.assertFalse((bundle / key.name).exists())
            (bundle / 'Data/disk.qcow2').write_bytes(b'changed disk')
            with self.assertRaisesRegex(ValueError, 'changed'): package.verify(bundle, public)
            (bundle / 'release.sig').write_bytes(bytes(64))
            with self.assertRaises(subprocess.CalledProcessError): package.verify(bundle, public)

    def test_setup_journal_is_private_atomic_and_password_free(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'setup.json'
            data = {'format': 1, 'name': 'chris', 'phase': 'chosen', 'token': 'a' * 32}
            first.atomic(path, data)
            self.assertEqual(json.loads(path.read_text()), data)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(path.parent.glob('.setup-*')), [])


if __name__ == '__main__': unittest.main()
