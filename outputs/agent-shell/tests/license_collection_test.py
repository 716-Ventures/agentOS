import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('license_collection',ROOT/'collect_licenses.py');collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
class LicenseCollection(unittest.TestCase):
    def metadata(self,root,name='example',version='1.0.0'):
        return json.dumps({'packages':[{'id':'dependency','name':name,'version':version,'manifest_path':str(root/'Cargo.toml'),'source':'registry+https://github.com/rust-lang/crates.io-index','license':'MIT'}],'resolve':{'root':'dependency','nodes':[{'id':'dependency','deps':[]}]}})
    def test_collection_is_stable_and_missing_notices_preserve_the_previous_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'crate';source.mkdir();(source/'LICENSE').write_text('Upstream license and copyright notice')
            output=root/'notices'
            with patch.object(collector.subprocess,'check_output',return_value=self.metadata(source)):
                collector.collect([source/'Cargo.toml'],output);before=(output/'dependencies.json').read_bytes();collector.collect([source/'Cargo.toml'],output)
                self.assertEqual((output/'dependencies.json').read_bytes(),before)
                notices=json.loads(before)['packages'][0]['notices'];self.assertEqual((output/notices[0]['path']).read_text(),'Upstream license and copyright notice')
                (source/'LICENSE').unlink()
                with self.assertRaisesRegex(ValueError,'no packaged license'):collector.collect([source/'Cargo.toml'],output)
                self.assertEqual((output/'dependencies.json').read_bytes(),before)
    def test_pinned_supplemental_notice_is_recorded_without_relicensing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(collector.subprocess,'check_output',return_value=self.metadata(root,'drm-fourcc','2.2.0')):
                records=collector.collect([root/'Cargo.toml'],root/'notices')
            self.assertEqual(records[0]['license'],'MIT');self.assertIn('bb1b81f',records[0]['supplemental_notice']['notices'][0]['source'])
    def test_unrelated_output_directory_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'LICENSE').write_text('notice');output=root/'user';output.mkdir();(output/'keep').write_text('mine')
            with patch.object(collector.subprocess,'check_output',return_value=self.metadata(root)):
                with self.assertRaisesRegex(ValueError,'Refusing'):collector.collect([root/'Cargo.toml'],output)
            self.assertEqual((output/'keep').read_text(),'mine')
