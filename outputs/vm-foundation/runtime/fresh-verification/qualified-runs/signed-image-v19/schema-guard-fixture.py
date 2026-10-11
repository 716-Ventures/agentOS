"""Qualification-only probe against first-account live state and a signed older runtime."""
import importlib.util,json,os,subprocess,sys
from pathlib import Path
current=Path('/usr/local/lib/agent-os/current').resolve()
spec=importlib.util.spec_from_file_location('image_installer',current/'install_runtime.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
installer=module.Installer();older=sys.argv[1];legacy=installer.root/'releases'/older
assert 'component_schemas' not in installer.contract(legacy)
username=installer.login_user
activity=json.loads((Path('/home')/username/'image-activity.json').read_text())['id']
ident='image-schema-guard-'+os.urandom(12).hex()
def present(value):
 return json.loads(subprocess.check_output(['runuser','-u',username,'--','agent-os','presentation','-'],input=json.dumps(value).encode()))
def apply(key,expected,operations):
 return present({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':ident+'-'+key,'expected_revisions':{ident:expected},'operations':operations})
document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':ident,'activity_id':str(activity),'revision':0,'title':'Image schema guard','root':'button','elements':{'button':{'type':'Button@1','props':{'label':'Next image action λ','icon':'arrow-right','icon_position':'only','size':'xs'}}},'bindings':{},'actions':{}}
apply('create',None,[{'op':'surface.create','document':document}])
try:
 units=installer.contract(current)['units']
 def identities():return subprocess.check_output(['systemctl','show','--property=MainPID','--property=ActiveEnterTimestampMonotonic',*units],text=True)
 before=identities();journal=installer.journal.read_bytes();saved=present({'op':'presentation.get','document_id':ident})
 try:installer.activate(older)
 except ValueError as error:assert 'Button@1.icon' in str(error),error
 else:raise AssertionError('Image rollback permitted unsupported icon properties')
 assert Path('/usr/local/lib/agent-os/current').resolve()==current
 assert identities()==before and installer.journal.read_bytes()==journal
 assert present({'op':'presentation.get','document_id':ident})==saved
 apply('plain',saved['revision'],[{'op':'element.set_props','surface_id':ident,'element_id':'button','props':{'label':'Plain image action λ'}}])
 installer.compatible_components(installer.contract(legacy))
 for kind,value,extra in [('TextField@1','Saved',{}),('Choice@1','First',{'options':['First','Second λ']}),('Toggle@1',False,{})]:
  field={'type':kind,'props':{'label':'Image validation λ','value':value,**extra,'validation_message':'Choose another saved name.'}}
  saved=present({'op':'presentation.get','document_id':ident})
  apply('validation-'+kind.split('@')[0],saved['revision'],[{'op':'element.put','surface_id':ident,'element_id':'button','element':field}])
  saved=present({'op':'presentation.get','document_id':ident})
  try:installer.activate(older)
  except ValueError as error:assert kind+'.validation_message' in str(error),error
  else:raise AssertionError('Image rollback permitted unsupported '+kind+' validation properties')
  assert Path('/usr/local/lib/agent-os/current').resolve()==current
  assert identities()==before and installer.journal.read_bytes()==journal
  assert present({'op':'presentation.get','document_id':ident})==saved
  field['props'].pop('validation_message')
  apply('plain-'+kind.split('@')[0],saved['revision'],[{'op':'element.set_props','surface_id':ident,'element_id':'button','props':field['props']}])
  installer.compatible_components(installer.contract(legacy))
 report={'result':'pass','current_runtime':current.name,'legacy_runtime':older,'incompatible_icon_refused':True,'incompatible_text_choice_toggle_validation_refused':True,'live_service_identities_unchanged':True,'document_and_journal_unchanged':True,'plain_legacy_button_compatible':True}
 Path('/tmp/image-v19-schema-guard-result.json').write_text(json.dumps(report)+'\n')
 print('PASS: fresh image refuses saved icon-property rollback without stopping services or changing document/journal; plain legacy controls remain compatible; saved text/choice/toggle validation also refused',flush=True)
finally:
 saved=present({'op':'presentation.get','document_id':ident});apply('close',saved['revision'],[{'op':'surface.close','surface_id':ident}])
