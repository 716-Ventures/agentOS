"""Renderer-independent surface layout operations and validation."""
import copy
import math
import uuid

VIEWS = ('answer', 'output', 'history', 'jobs')


def surface(job=None, view='answer'):
    return {'id':uuid.uuid4().hex, 'job':job, 'view':view, 'scroll':0}


def leaves(tree):
    if 'id' in tree:return [tree]
    return leaves(tree['first'])+leaves(tree['second'])


def canonical(value):
    """Accept legacy terminal trees, discarding renderer-local scroll state."""
    ids=set()
    def node(t,depth=0):
        if not isinstance(t,dict) or depth>5:raise ValueError('Invalid layout tree')
        if 'id' in t:
            ident=t['id'];job=t.get('job');view=t.get('view','answer')
            if (not isinstance(ident,str) or not 1<=len(ident)<=64 or not ident.isalnum() or ident in ids
                or view not in VIEWS or (job is not None and (type(job) is not int or job<=0))):
                raise ValueError('Invalid or duplicate surface')
            ids.add(ident)
            return {'id':ident,'job':job,'view':view,'scroll':0}
        ratio=t.get('ratio')
        if t.get('axis') not in ('x','y') or type(ratio) not in (int,float) or not math.isfinite(ratio) or not .15<=ratio<=.85:
            raise ValueError('Invalid split')
        return {'axis':t['axis'],'ratio':ratio,'first':node(t.get('first'),depth+1),'second':node(t.get('second'),depth+1)}
    tree=node(value['tree'])
    if len(ids)>6:raise ValueError('At most six surfaces are supported')
    focus=value.get('focus') or leaves(tree)[0]['id']
    zoom=value.get('zoom')
    if focus not in ids or (zoom is not None and zoom not in ids):raise ValueError('Focus or maximized surface is missing')
    return {'tree':tree,'focus':focus,'zoom':zoom}


def replace(tree,ident,new):
    if tree.get('id')==ident:return new
    if 'id' not in tree:
        tree['first']=replace(tree['first'],ident,new);tree['second']=replace(tree['second'],ident,new)
    return tree


def remove(tree,ident):
    if 'id' in tree:return tree
    if tree['first'].get('id')==ident:return tree['second']
    if tree['second'].get('id')==ident:return tree['first']
    tree['first']=remove(tree['first'],ident);tree['second']=remove(tree['second'],ident)
    return tree


def parent(tree,ident):
    if 'id' in tree:return None
    if any(tree[k].get('id')==ident for k in ('first','second')):return tree
    return parent(tree['first'],ident) or parent(tree['second'],ident)


def apply(state,action):
    result=copy.deepcopy(state)
    operation=action.get('operation')
    specs={'split':{'surface_id','axis','view','job_id'},'close':{'surface_id'},
           'focus':{'surface_id'},'zoom':{'surface_id'},'restore':set(),
           'resize':{'surface_id','delta'},'swap':{'surface_id','other_id'},
           'bind':{'surface_id','job_id','view'},'view':{'surface_id','view'}}
    if operation not in specs or set(action)-specs[operation]-{'operation'}:raise ValueError('Unknown operation or argument')
    surfaces=leaves(result['tree']);ident=action.get('surface_id')
    tile=next((p for p in surfaces if p['id']==ident),None)
    if operation!='restore' and tile is None:raise ValueError('Surface not found; refresh the layout')
    if operation=='split':
        if len(surfaces)>=6:raise ValueError('At most six surfaces are supported')
        if action.get('axis') not in ('x','y'):raise ValueError('Split axis must be x or y')
        new=surface(action.get('job_id'),action.get('view',tile['view']))
        result['tree']=replace(result['tree'],ident,{'axis':action['axis'],'ratio':.5,'first':tile,'second':new})
        result.update(focus=new['id'],zoom=None)
    elif operation=='close':
        if len(surfaces)==1:raise ValueError('Keep at least one surface open')
        result['tree']=remove(result['tree'],ident)
        if result['focus']==ident:result['focus']=leaves(result['tree'])[0]['id']
        if result['zoom']==ident:result['zoom']=None
    elif operation=='focus':
        result['focus']=ident
        if result['zoom'] is not None:result['zoom']=ident
    elif operation=='zoom':result.update(focus=ident,zoom=ident)
    elif operation=='restore':result['zoom']=None
    elif operation=='resize':
        split=parent(result['tree'],ident);delta=action.get('delta')
        if split is None:raise ValueError('Split this surface before resizing')
        if type(delta) not in (int,float) or not math.isfinite(delta) or not -.25<=delta<=.25:raise ValueError('Resize delta must be between -0.25 and 0.25')
        if split['second'].get('id')==ident:delta=-delta
        split['ratio']=round(max(.15,min(.85,split['ratio']+delta)),3)
    elif operation=='swap':
        other=next((p for p in surfaces if p['id']==action.get('other_id')),None)
        if other is None:raise ValueError('Other surface not found')
        # Move entire stable surfaces, not just their content bindings.
        old_a,old_b=copy.deepcopy(tile),copy.deepcopy(other)
        temporary=uuid.uuid4().hex
        result['tree']=replace(result['tree'],ident,{'id':temporary})
        result['tree']=replace(result['tree'],other['id'],old_a)
        result['tree']=replace(result['tree'],temporary,old_b)
    elif operation=='bind':
        tile['job']=action.get('job_id');tile['view']=action.get('view',tile['view'])
    elif operation=='view':tile['view']=action.get('view')
    return canonical(result)
