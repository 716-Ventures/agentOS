import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('build_runtime', Path(__file__).resolve().parents[1]/'build_runtime.py')
build_runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_runtime)


@unittest.skipUnless(shutil.which('cargo'), 'Cargo is required for the build-cache regression')
class RestoredSourceBuildTest(unittest.TestCase):
    def test_restored_older_source_rebuilds_current_bytes_and_retires_debug_artifacts(self):
        with tempfile.TemporaryDirectory(prefix='agentos-cache-regression-') as directory:
            root = Path(directory)
            (root/'src').mkdir()
            manifest = root/'Cargo.toml'
            manifest.write_text('[package]\nname="agentos-cache-fixture"\nversion="0.1.0"\nedition="2021"\n')
            source = root/'src/main.rs'
            source.write_text('fn main() { println!("first"); }\n')
            stamp = source.stat()
            def cargo(*args):
                return subprocess.run(['cargo', *args, '--manifest-path', str(manifest)], check=True, capture_output=True)
            cargo('build')
            cargo('build', '--release')
            binary = root/'target/release/agentos-cache-fixture'
            self.assertEqual(subprocess.check_output([binary], text=True).strip(), 'first')
            source.write_text('fn main() { println!("other"); }\n')
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            cargo('build', '--release')
            self.assertEqual(subprocess.check_output([binary], text=True).strip(), 'first', 'Baseline must reproduce Cargo accepting the restored timestamp')
            build_runtime.build_release(manifest, 'agentos-cache-fixture')
            self.assertEqual(subprocess.check_output([binary], text=True).strip(), 'other')
            self.assertFalse((root/'target/debug/agentos-cache-fixture').exists())
