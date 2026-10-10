"""Read complete runtime history through byte-bounded, revision-consistent pages."""
def _read(request,activity,stopped,collections,recent=False):
    for attempt in range(3):
        try:
            state={};revision=None
            for collection in collections:
                rows=[];before=None
                while True:
                    if stopped():raise RuntimeError('Runtime read cancelled')
                    fields={'collection':collection,'limit':64,'before_id':before}
                    if collection=='jobs' and recent:fields['recent_only']=True
                    if collection!='activities' and activity is not None:fields['activity_id']=int(activity)
                    if revision is not None:fields['expected_revision']=revision
                    page=request('state.page',**fields)
                    observed=page.get('revision')
                    if type(observed) is not int or observed<0:raise RuntimeError('Invalid runtime revision')
                    if revision is not None and observed!=revision:raise RuntimeError('resync_required')
                    revision=observed;state.update(revision=revision,version=page.get('version'),mode=page.get('mode'))
                    entries=page.get('rows')
                    if not isinstance(entries,list):raise RuntimeError('Invalid runtime page')
                    previous=before if before is not None else 2**63-1
                    for row in entries:
                        ident=row.get('id') if isinstance(row,dict) else None
                        if type(ident) is not int or not 0<ident<previous:raise RuntimeError('Invalid runtime row cursor')
                        previous=ident
                    rows.extend(entries)
                    next_id=page.get('next_before_id')
                    if next_id is None:break
                    if not entries or type(next_id) is not int or next_id!=previous:raise RuntimeError('Invalid runtime page cursor')
                    before=next_id
                state[collection]=rows
            return state
        except RuntimeError as exc:
            if 'resync_required' not in str(exc) or attempt==2:raise


def read(request,activity=None,stopped=lambda:False,recent=False):
    return _read(request,activity,stopped,('activities','jobs'),recent)


def history(request,activity,stopped=lambda:False):
    return _read(request,activity,stopped,('events',))['events']
