from pathlib import Path
import subprocess,json
root=Path('/home/developer/agent-os-source/tests')
p=root/'direct_table_probe.py';original=p.read_bytes()
observer=root/'direct_input_probe.py';original_observer=observer.read_bytes()
traced=original_observer.decode().replace('selected=focused=False;ancestor=cell','selected=focused=False;active=False;ancestor=cell').replace('focused=focused or state.contains(pyatspi.STATE_FOCUSED)','focused=focused or state.contains(pyatspi.STATE_FOCUSED);active=active or state.contains(pyatspi.STATE_ACTIVE)').replace("'selected':selected,'focused':focused}","'selected':selected,'focused':focused,'active':active}")
s=original.decode().replace('import uuid','import uuid\nimport sqlite3')
s=s.replace("    def update(rows, blocked=False):",'''    def diagnostic(phase):
        with sqlite3.connect('file:/var/lib/agent-os-runtime/state.sqlite3?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            leases=db.execute('SELECT document,element,uid,session,expires FROM presentation_leases WHERE document=?',(surface,)).fetchall()
        observed=scene()
        print('LEASE_DIAGNOSTIC: '+json.dumps({'phase':phase,'wall':time.time(),'monotonic_ns':time.monotonic_ns(),'leases':leases,'seat_focus':observed['seat_focus'],'window':window(surface),'selected_cell':observe('table-cell:Document λ 日本語') if phase != 'selected-Updated λ 日本語' else observe('table-cell:Updated λ 日本語')}),flush=True)

    def update(rows, blocked=False):''')
a=s.index("    def update(rows, blocked=False):");s=s[:a]+s[a:].replace("            try:\n                result = presentation({'op': 'presentation.apply'", "            try:\n                if blocked:diagnostic('before-blocked-update')\n                result = presentation({'op': 'presentation.apply'")
s=s.replace("            assert not blocked, 'Focused Table update bypassed its interaction guard'", "            if blocked:diagnostic('after-accepted-update')\n            assert not blocked, 'Focused Table update bypassed its interaction guard'")
s=s.replace("        wait(lambda: observe('table-cell:' + label)['selected'], 'Kernel pointer did not select the Table row')", "        wait(lambda: observe('table-cell:' + label)['selected'], 'Kernel pointer did not select the Table row')\n        diagnostic('selected-'+label)")
s=s.replace("        wait(lambda: menu_enabled(), 'Kernel Shift+F10 did not open the Table menu')", "        wait(lambda: menu_enabled(), 'Kernel Shift+F10 did not open the Table menu')\n        diagnostic('copy-menu-showing')")
try:
 p.write_text(s)
 observer.write_text(traced)
 results=[]
 for index in range(4):
  r=subprocess.run(['python3',str(root/'direct_display_guest.py'),'--list-input'],capture_output=True,text=True,timeout=120)
  (Path('/tmp')/('agentos-list-lease-diagnostic-v2-'+str(index)+'.log')).write_text(r.stdout+r.stderr)
  results.append({'index':index,'returncode':r.returncode})
  if r.returncode:break
 print(json.dumps(results),flush=True)
finally:
 observer.write_bytes(original_observer)
 p.write_bytes(original)
 assert p.read_bytes()==original
