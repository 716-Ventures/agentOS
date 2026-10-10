"""Independent AT-SPI journey through the running desktop and real core."""
from collections import deque
import time
import pyatspi


def wait(predicate,description):
    end=time.monotonic()+10
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.05)
    raise AssertionError(description)


def find(name,role):
    found=[]
    def search():
        queue=deque([pyatspi.Registry.getDesktop(0)])
        visited=0
        while queue and visited<4096:
            node=queue.popleft();visited+=1
            try:
                if node.name==name and node.getRole()==role:
                    found.append(node);return True
                queue.extend(node[index] for index in range(min(node.childCount,128)))
            except (RuntimeError,LookupError):pass
        return False
    wait(search,'Accessible control missing: '+name)
    return found[0]


def text(node):
    value=node.queryText()
    return value.getText(0,value.characterCount)


def activate(node):
    assert node.getState().contains(pyatspi.STATE_ENABLED)
    action=node.queryAction();assert action.nActions>0
    assert action.doAction(0)


def verify(call):
    field=find('Accessible session draft',pyatspi.ROLE_TEXT)
    assert text(field)=='Original accessible value'
    def saved():
        return call({'op':'presentation.snapshot'})['documents']['session-fixture']['elements']['field']['props']['value']
    def draft():
        return call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'}).get('draft')
    value='AT-SPI saved λ 日本語'
    assert field.queryEditableText().setTextContents(value)
    wait(lambda:draft()==value,'Accessible edit was not retained by core')
    assert saved()=='Original accessible value','Editing committed without deliberate save'
    activate(find('Save draft',pyatspi.ROLE_PUSH_BUTTON))
    wait(lambda:saved()==value,'Accessible Save did not commit the exact Unicode draft')
    assert field.queryEditableText().setTextContents('Discard this accessible edit')
    wait(lambda:draft()=='Discard this accessible edit','Second edit was not retained')
    activate(find('Discard draft',pyatspi.ROLE_PUSH_BUTTON))
    wait(lambda:draft() is None and text(field)==value,'Accessible Discard did not restore committed text')
    assert saved()==value
    print('PASS: independent AT-SPI desktop Unicode editing, deliberate save, discard and real core state')
