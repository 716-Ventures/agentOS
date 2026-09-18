import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import model_usage as usage
import providers

class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name in ('STATE','PUBLIC'):
            p=patch.object(usage,name,Path(self.tmp.name)/name)
            p.start();self.addCleanup(p.stop)
        usage.configure({'gateway_key':'SECRET','gateway_model':'paid/model','jev_key':'SECRET'},'default')
    def test_attempts_failures_unknown_tokens_and_restart(self):
        url=providers.GATEWAY+'/chat/completions'
        key=usage.begin(url,{'model':'paid/model','messages':['private']})
        usage.finish(key,.2,{'model':'resolved/model','usage':{'prompt_tokens':12,'completion_tokens':3,'total_tokens':15}})
        usage.finish(usage.begin(url,{'model':'paid/model'}),.4,http_status=429)
        usage.finish(usage.begin(url,{'model':'paid/model'}),.1,{'usage':{}})
        usage.begin(url,{'model':'paid/model'})
        usage.configure({},'default',recover=True)
        data=usage.read();row=data['models'][key]
        self.assertEqual((row['attempts'],row['responses'],row['errors'],row['rate_limits'],row['interrupted'],row['active']),(4,2,1,1,1,0))
        self.assertEqual((row['total_tokens'],row['total_reports']),(15,1))
        self.assertNotIn('SECRET',usage.PUBLIC.read_text())
        self.assertNotIn('private',usage.PUBLIC.read_text())
        self.assertEqual(usage.PUBLIC.stat().st_mode & 0o777,0o640)
    def test_gets_not_counted_and_telemetry_failure_nonfatal(self):
        self.assertIsNone(usage.begin(providers.GATEWAY+'/models',None))
        with patch.object(usage,'STATE',Path(self.tmp.name)/'missing'/'state'):
            self.assertIsNone(usage.begin(providers.GATEWAY+'/chat/completions',{'model':'x'}))
    def test_http_boundary_tracks_failure(self):
        import urllib.error
        error=urllib.error.HTTPError('url',429,'rate limit',{},None)
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(providers.RateLimited):
                providers.http_json(providers.GATEWAY+'/chat/completions',{'model':'test'},'SECRET')
        row=list(usage.read()['models'].values())[0]
        self.assertEqual(row['rate_limits'],1)
        self.assertEqual(row['active'],0)

if __name__=='__main__':unittest.main()
