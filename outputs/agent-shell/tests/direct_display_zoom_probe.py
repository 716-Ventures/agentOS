"""Display zoom through real kernel shortcuts and pointer operation."""
import math
import time


def verify(scene, target, snapshot, keyboard, pointer, wait):
    before=scene();output=before['outputs'][0]
    def zoom(factor):
        deadline=time.monotonic()+8
        while True:
            state=scene()
            if state['display_zoom']==factor and state['outputs'][0]['width']==math.ceil(output['width']/factor):return state
            assert time.monotonic()<deadline,('Display zoom did not settle',state)
            time.sleep(.05)
    for factor in (1.25,1.5,1.75,2.0):
        keyboard.chord(29,56,13) # Ctrl+Alt+Equals
        zoom(factor)
    state=scene();scaled=state['outputs'][0]
    assert scaled['height']==output['height']//2,state
    assert state['seat_focus']==target,state
    keyboard.chord(29,56,37) # Ctrl+Alt+K
    def layer(mapped):
        deadline=time.monotonic()+8
        while True:
            state=scene()
            layers=[item for item in state['system_layers'] if item['namespace']=='agentos-keyboard' and item['mapped']]
            if bool(layers)==mapped:
                if not mapped:return state,None
                if layers[0]['geometry']['height']<=scaled['height']/2:return state,layers[0]
            assert time.monotonic()<deadline,('Zoomed keyboard did not settle',state)
            time.sleep(.05)
    state,keys=layer(True)
    assert keys['work_area']['height']>0,keys
    def click(name):
        _,keys=layer(True);point=snapshot('keyboard:'+name)['point']
        pointer.click(point[0]+keys['geometry']['x'],point[1]+keys['geometry']['y'],scaled['width'],scaled['height'])
    click('a');wait(lambda value:value['text']=='a' and value['focused'])
    assert scene()['seat_focus']==target
    def scroll_to(name,axis,direction):
        # Wheel input over the key body must expose controls outside its viewport.
        _,keys=layer(True)
        x=scaled['width']//2;y=keys['geometry']['y']+keys['geometry']['height']-30
        pointer.event(3,0,round(x*65535/scaled['width']));pointer.event(3,1,round(y*65535/scaled['height']));pointer.sync()
        if pointer.motion_ready:pointer.motion_ready(x,y)
        for _ in range(30):
            point=snapshot('keyboard:'+name)['point']
            if axis==8 and 52<point[1]<keys['geometry']['height']-12:return
            if axis==6 and 12<point[0]<scaled['width']-12:return
            pointer.event(2,axis,direction);pointer.sync();time.sleep(.05)
        raise AssertionError(('Scrolled keyboard control never became reachable',name,point,keys))
    scroll_to('Shift',8,-1)
    click('Shift');click('Shift on')
    scroll_to('Backspace',8,1)
    scroll_to('Backspace',6,1)
    click('Backspace');wait(lambda value:value['text']=='')
    click('Hide keyboard');layer(False)
    keyboard.chord(29,56,12) # Ctrl+Alt+Minus
    zoom(1.75)
    keyboard.chord(29,56,11) # Ctrl+Alt+Zero
    restored=zoom(1.0)
    assert restored['outputs']==before['outputs'],restored
    assert restored['seat_focus']==target and restored['keyboard_pressed_count']==0,restored
    assert next(item['work_area'] for item in restored['system_layers'] if item['namespace']=='agentos-system-bar')==next(item['work_area'] for item in before['system_layers'] if item['namespace']=='agentos-system-bar')
    print('PASS: kernel display zoom changes logical geometry, scaled pointer typing, wheel access to modifier/edit keys and keyboard dismissal work; zoom-out and exact reset preserve focus and workspace',flush=True)
