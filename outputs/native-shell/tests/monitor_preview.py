#!/usr/bin/python3
"""Explicitly synthetic monitor visual cases. Run under dbus-run-session."""
import os,json,subprocess,time,tempfile,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'test-output/monitor-preview';out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='agentos-design-') as directory:
    runtime=Path(directory);env={**os.environ,'XDG_RUNTIME_DIR':directory,'WAYLAND_DISPLAY':'design-test','GDK_BACKEND':'wayland','GSK_RENDERER':'cairo','GTK_A11Y':'atspi','G_DEBUG':'fatal-criticals'}
    displaylog=(out/'weston.log').open('w');display=subprocess.Popen(['weston','--backend=headless-backend.so','--use-pixman','--socket=design-test','--idle-time=0','--width=1600','--height=1200'],env=env,stdout=displaylog,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        for _ in range(100):
            if (runtime/'design-test').exists():break
            assert display.poll() is None;time.sleep(.05)
        subprocess.run(['cargo','test','--offline','selected_agent_controls_keep_exact_job_identity','--','--ignored','--nocapture'],cwd=ROOT,env=env,check=True,timeout=90)
        jobs=[];agents={}
        for i,(name,status,prompt) in enumerate([('Workspace','running','Organize the project notes and prepare a concise summary.'),('System','succeeded','Check the available disk space.'),('Research','failed','Find the supporting references for this proposal.')],1):
            jobs.append({'id':i,'activity_id':i,'argv':['/usr/bin/python3','-u','/usr/local/lib/agent-os/services/worker.py','ask',str(i),prompt],'status':status,'created_at':1791800100,'finished_at':1791800200 if i>1 else None,'error':'Provider connection failed. Try again when the connection is available.' if i==3 else None})
            agents[str(i)]={'models':{'gateway/model':{'model':'inclusionai/ling-3.0-flash-vl-free','provider':'Vercel AI Gateway','input_tokens':1200*i,'output_tokens':340*i,'total_tokens':1540*i,'input_reports':1,'output_reports':1,'total_reports':1,'responses':1}}}
        fixture={'connected':True,'core':{'jobs':jobs,'activities':[{'id':i,'name':name} for i,name in enumerate(['Workspace','System','Research'],1)]},'usage':{'agents':agents,'current_session':'fixture','sessions':{'fixture':{'models':{'gateway/model':{'responses':3,'total_reports':3,'total_tokens':9240}}}}}}
        for appearance,scale,width,height in [('dark',1,920,755),('light',1,920,755),('dark',1,640,520),('dark',2,800,600)]:
            name=f'{appearance}-{scale}-{width}';config=runtime/name/'agent-os';config.mkdir(parents=True)
            (config/'desktop.json').write_text(json.dumps({'appearance':appearance,'text_scale':scale,'reduced_motion':True}))
            value={**fixture,'width':width,'height':height,'capture':str(out/(name+'.png'))}
            path=runtime/(name+'.json');path.write_text(json.dumps(value))
            with (out/(name+'.log')).open('w') as log:
                subprocess.run([str(ROOT/'target/debug/agent-os-desktop'),'--desktop-preview',str(path),'--socket',str(runtime/'unused.sock')],env={**env,'XDG_CONFIG_HOME':str(config.parent)},stdout=log,stderr=subprocess.STDOUT,check=True,timeout=15)
    finally:
        if display.poll() is None:os.killpg(display.pid,signal.SIGTERM)
        display.wait(timeout=5);displaylog.close()
print('Rendered all four cases; preview inputs are explicitly synthetic verification data.')
