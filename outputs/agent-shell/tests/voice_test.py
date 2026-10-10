import base64
import io
import json
from pathlib import Path
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
import voice
import voice_input
import grounding


def wav(frames=16000,channels=1,width=2,rate=16000):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as output:
        output.setnchannels(channels);output.setsampwidth(width);output.setframerate(rate)
        output.writeframes(bytes(frames*channels*width))
    return buffer.getvalue()

class AudioTests(unittest.TestCase):
    def test_bounded_wave_format_and_truncation(self):
        self.assertEqual(len(voice.pcm_from_wav(wav())),32000)
        for raw in (b'invalid',wav(frames=160001),wav(frames=10),wav(channels=2),wav(width=1),wav(rate=8000),wav()[:-2]):
            with self.assertRaises(ValueError):voice.pcm_from_wav(raw)
    def test_silence_never_invokes_decoder_or_manufactures_words(self):
        service=voice.Voice.__new__(voice.Voice)
        with patch.object(voice.subprocess,'Popen') as spawn:
            result=service.transcribe(bytes(32000),(1000,'native'))
        self.assertEqual(result['status'],'no_signal');self.assertEqual(result['text'],'');spawn.assert_not_called()
    def test_rms_has_normalized_meaning(self):
        self.assertEqual(voice.level(bytes(100)),0)
        self.assertAlmostEqual(voice.level(struct.pack('<hh',16384,-16384)),.5)
    def test_daemon_peers_cannot_activate_microphone(self):
        service=voice.Voice.__new__(voice.Voice)
        for op in ('capture.start','transcribe','capture.finish'):
            with self.assertRaisesRegex(ValueError,'native user'):service.handle({'op':op,'wav_base64':base64.b64encode(wav()).decode()},(999,'agent'))
    def test_recognition_concurrency_is_bounded(self):
        service=voice.Voice.__new__(voice.Voice);service.busy=threading.Lock();service.busy.acquire()
        with self.assertRaisesRegex(ValueError,'busy'):service.transcribe(struct.pack('<h',1000)*16000,(1000,'native'))

class GroundingTests(unittest.TestCase):
    def context(self):
        return {'input_id':'a'*32,'captured_at':time.time(),'modality':'voice','activity_id':1,
            'surface_id':'tile-a','surface_title':'Output','selection_kind':'focused_output','layout_revision':4,
            'job_ref':'broker:'+'b'*32,'selection':'Untrusted command output','expected_generation':2}
    def test_context_keeps_original_identity_timestamp_and_evidence(self):
        context=self.context();validated=grounding.validate(context,1)
        self.assertEqual(validated,context);self.assertIsNot(validated,context)
    def test_invalid_referents_and_revisions_are_rejected(self):
        for change in ({'activity_id':2},{'captured_at':float('nan')},{'captured_at':time.time()+100},
            {'layout_revision':True},{'expected_generation':-1},{'actor':'human'},{'job_ref':'/tmp/other'},
            {'input_id':'unknown'},{'selection':'x'*12001}):
            with self.assertRaises(ValueError):grounding.validate({**self.context(),**change},1)

class VoiceInputTests(unittest.TestCase):
    def test_cancelled_recording_cannot_deliver_a_late_transcript(self):
        client=voice_input.VoiceInput();client.state='recording';client.token='token';client.epoch=1
        entered=threading.Event();release=threading.Event()
        def request(op,**fields):
            if op=='capture.finish':entered.set();release.wait(2);return {'text':'old transcript'}
            return {'state':'idle'}
        with patch.object(voice_input,'request',side_effect=request):
            client.finish();self.assertTrue(entered.wait(1));client.cancel();release.set()
            deadline=time.monotonic()+1
            while threading.active_count()>1 and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(client.snapshot()['state'],'idle');self.assertIsNone(client.snapshot()['result'])

if __name__=='__main__':unittest.main()
