"""Actual kernel pointer operation of the trusted on-screen keyboard."""
import time


def verify(output, scene, target, snapshot, keyboard, pointer, wait):
    width,height=output['width'],output['height']
    before=scene()
    area=next(layer['work_area'] for layer in before['system_layers'] if layer['namespace']=='agentos-system-bar')
    def mapped(expected):
        deadline=time.monotonic()+8
        while True:
            state=scene()
            layers=[layer for layer in state['system_layers'] if layer['namespace']=='agentos-keyboard' and layer['mapped']]
            if bool(layers)==expected:return state,layers[0] if layers else None
            assert time.monotonic()<deadline,('Keyboard did not change visibility',state)
            time.sleep(.05)
    keyboard.chord(29,56,37) # Ctrl+Alt+K
    state,layer=mapped(True)
    assert state['seat_focus']==target,state
    assert layer['work_area']['height']<area['height'],layer
    def click(name):
        _,layer=mapped(True)
        point=snapshot('keyboard:'+name)['point']
        pointer.click(point[0]+layer['geometry']['x'],point[1]+layer['geometry']['y'],width,height)
    click('a');wait(lambda value:value['text']=='a' and value['focused'])
    assert scene()['seat_focus']==target
    click('Shift');click('A');wait(lambda value:value['text']=='aA')
    click('Shift on');click('Backspace');wait(lambda value:value['text']=='a')
    keyboard.event(1,42,1);keyboard.sync() # A held physical modifier must survive an OSK click.
    try:
        deadline=time.monotonic()+5
        while scene()['keyboard_pressed_count']!=1:
            assert time.monotonic()<deadline
            time.sleep(.05)
        click('a')
        deadline=time.monotonic()+5
        while 'Release physical keys' not in snapshot('keyboard-status')['text']:
            assert time.monotonic()<deadline,'Held physical key was not rejected'
            time.sleep(.05)
        assert snapshot()['text']=='a'
        assert scene()['keyboard_pressed_count']==1,'OSK released a physical modifier'
    finally:
        keyboard.event(1,42,0);keyboard.sync()
    import direct_multi_keyboard_probe
    direct_multi_keyboard_probe.verify(scene,snapshot,keyboard,click,wait)
    keyboard.chord(29,30);keyboard.chord(14)
    wait(lambda value:value['text']=='')
    click('Hide keyboard')
    restored,_=mapped(False)
    assert restored['seat_focus']==target,restored
    assert next(layer['work_area'] for layer in restored['system_layers'] if layer['namespace']=='agentos-system-bar')==area
    assert restored['keyboard_pressed_count']==0,restored
    # A bar click temporarily takes seat focus. Invoking the keyboard there
    # must restore its exact previous application rather than type into the bar.
    bar=next(layer for layer in restored['system_layers'] if layer['namespace']=='agentos-system-bar')
    pointer.click(width//2,bar['geometry']['height']//2,width,height)
    deadline=time.monotonic()+5
    while scene()['seat_focus']!=bar['id']:
        assert time.monotonic()<deadline
        time.sleep(.05)
    keyboard.chord(29,56,37)
    state,_=mapped(True)
    deadline=time.monotonic()+5
    while state['seat_focus']!=target:
        assert time.monotonic()<deadline,('Bar shortcut did not restore focus',state)
        time.sleep(.05);state=scene()
    click('Hide keyboard');mapped(False)
    print('PASS: kernel on-screen keyboard shortcut/pointer typing, Shift/edit, held physical key isolation, focus retention and work-area restoration',flush=True)
