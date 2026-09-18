"""Guest: real broker + Jev; scripted dispatcher exercise, isolated conversation state."""
import sys,json,socket,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'/usr/local/lib/agent-os/services')
import assistant
results=[]
def scripted(prompt,history,cfg,dispatch,progress,record):
 args={'argv':['/usr/bin/touch','new-note.txt'],'scope':'workspace','purpose':'Inspect creation effects'}
 results.append(dispatch('preview_execution',args))
 results.append(dispatch('preview_execution',args))
 results.append(dispatch('execute',args))
 allowed=dispatch('preview_execution',{'argv':['/usr/bin/apt-get','install','git'],'scope':'system','purpose':'Check install policy'})
 assert 'jev' not in allowed
 return {'messages':[{'role':'user','content':prompt},{'role':'assistant','content':'Verification complete.'}],'text':'Verification complete.','model':'scripted-dispatch-test','finish_reason':'stop'}
with tempfile.TemporaryDirectory() as directory, socket.socketpair()[0] as conn:
 # emit is mocked only to avoid needing a stream consumer; inference advice remains live.
 with patch.object(assistant,'STATE',Path(directory)),patch.object(assistant,'emit'),patch.object(assistant,'send'),patch.object(assistant,'run_agent',side_effect=scripted),patch.object(assistant,'jev_review',wraps=assistant.jev_review) as review:
  assistant.handle({'op':'ask','activity':2,'prompt':'Inspect only'},conn)
  assert review.call_count==1,review.call_count
  assert results[0]['decision']=='inspect'
  assert results[0]['jev']['status']=='available',results[0]
  assert results[2]['status']=='inspection_required'
  assert results[2]['policy']['jev']['authorizes_execution'] is False
  trace=json.loads(next(Path(directory).glob('agent-*.json')).read_text())
  assert sum(e['kind']=='jev_advisory' for e in trace['events'])==1
print(json.dumps({'passed':True,'checks':['live Jev advisory through assistant dispatch','cached across preview and execute','broker inspection decision unchanged','known install needs no Jev call','advisory recorded in trace'],'reasoning_model':'scripted test; no Ling inference'}))
