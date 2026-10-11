from pathlib import Path
s=Path('outputs/agent-shell/tests/direct_input_probe.py').read_text()
block='''            if request=='launcher-diagnostic':
                from gi.repository import Gio,GLib
                connection=Gio.DBusConnection.new_for_address_sync(os.environ['AT_SPI_BUS_ADDRESS'],Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
                rows=[]
                for name,role in [('Agent launcher',pyatspi.ROLE_FRAME),('Ask Agent',pyatspi.ROLE_TEXT)]:
                    try:
                        node=find(name,role)
                        for depth in range(8):
                            if node is None:break
                            row={'target':name,'depth':depth,'name':node.name,'role':node.getRoleName(),'path':node.path,'bus':node.app.bus_name,'focused':node.getState().contains(pyatspi.STATE_FOCUSED)}
                            try:
                                row['wire_parent']=connection.call_sync(node.app.bus_name,node.path,'org.freedesktop.DBus.Properties','Get',GLib.Variant('(ss)',('org.a11y.atspi.Accessible','Parent')),None,Gio.DBusCallFlags.NONE,1000,None).unpack()
                            except Exception as error:row['wire_error']=str(error)
                            rows.append(row);node=node.parent
                    except Exception as error:rows.append({'target':name,'error':str(error)})
                print(json.dumps({'rows':rows}),flush=True);continue
'''
s=s.replace("            if request=='tree':",block+"            if request=='tree':")
s=s.replace("                opened=layer_state(True)","                opened=layer_state(True)\n                if screen_reader:\n                    print('LAUNCHER_DIAGNOSTIC cycle='+str(cycle)+' '+json.dumps(snapshot('launcher-diagnostic')),flush=True)")
Path('/tmp/agentos-v17-diagnostic-direct_input_probe.py').write_text(s)
s=Path('outputs/agent-shell/tests/direct_screen_reader_probe.py').read_text().replace("        await_speech(lambda text:'Ask Agent' in text[baseline:]", "        print('LAUNCHER_DIAGNOSTIC reader '+str(snapshot('launcher-diagnostic')),flush=True)\n        await_speech(lambda text:'Ask Agent' in text[baseline:]")
Path('/tmp/agentos-v17-diagnostic-direct_screen_reader_probe.py').write_text(s)
