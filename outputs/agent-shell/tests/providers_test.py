#!/usr/bin/env python3
"""Contract tests use labelled fixtures, never substitute them for live API results."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services'))
import providers as p

class Contracts(unittest.TestCase):
    def test_free_price_guard(self):
        for price in ({}, {'input':'0'}, {'input':'0','output':'.01'},
                      {'input':'0','output':'0','varies_by_provider':True},
                      {'input':'NaN','output':'0'}):
            self.assertFalse(p.is_free({'type':'language','pricing':price}))
        self.assertTrue(p.is_free({'type':'language','pricing':{'input':'0','output':'0'}}))

    def test_no_paid_completion_request(self):
        with patch.object(p,'http_json',return_value={'data':[]}) as call:
            with self.assertRaises(p.ProviderError):
                p.explain('Inspect',{}, {'gateway_key':'fixture-not-a-key'})
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args,(p.GATEWAY+'/models',))

    def test_missing_keys_make_no_network_calls(self):
        with patch.object(p,'http_json') as call:
            with self.assertRaises(p.ProviderError): p.route('inspect',False,{})
            with self.assertRaises(p.ProviderError): p.explain('inspect',{}, {})
            call.assert_not_called()

    def test_jev_typed_route(self):
        fixture={'model':p.JEV_MODEL,'answers':{'intent':{'type':'choice','choice':'inspect_disk','confidence':.95}}}
        with patch.object(p,'http_json',return_value=fixture) as call:
            result=p.route('Where is my space?',False,{'jev_key':'fixture-not-a-key'})
            self.assertEqual(result['choice'],'inspect_disk')
            self.assertEqual(set(call.call_args.args[1]['questions']['intent']['criteria']),set(p.CHOICES))
        fixture['answers']['intent']['choice']='run_shell'
        with patch.object(p,'http_json',return_value=fixture):
            with self.assertRaises(p.ProviderError): p.route('anything',False,{'jev_key':'fixture-not-a-key'})

    def test_ambiguous_route_does_not_dispatch(self):
        fixture={'answers':{'intent':{'type':'choice','choice':'inspect_disk','confidence':.2}}}
        with patch.object(p,'http_json',return_value=fixture):
            self.assertEqual(p.route('something',False,{'jev_key':'fixture-not-a-key'})['choice'],'unsupported')

    def test_explanation_contract(self):
        fixture={'choices':[{'message':{'content':'Fixture explanation [FS]'},'finish_reason':'stop'}]}
        with patch.object(p,'require_free'), patch.object(p,'http_json',return_value=fixture) as call:
            result=p.explain('why?',{'filesystem':{'used_bytes':123}}, {'gateway_key':'fixture-not-a-key'})
            self.assertIn('[FS]', result['text'])
            body=call.call_args.args[1]
            self.assertNotIn('tools',body)
            self.assertEqual(json.loads(body['messages'][1]['content'])['measured_report']['filesystem']['used_bytes'],123)

if __name__=='__main__': unittest.main()
