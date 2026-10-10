"""Bounded shared document reads, reconciled against one presentation journal cursor."""

def read(request,activity=None,metadata=True,stopped=lambda:False):
    scope={} if activity is None else {'activity_id':str(activity)}
    for attempt in range(3):
        documents={};after='';cursor=None
        try:
            while True:
                if stopped():raise RuntimeError('Presentation read cancelled')
                fields={**scope,'after_id':after,'limit':16}
                if cursor is not None:fields['expected_cursor']=cursor
                page=request('presentation.page',**fields)
                cursor=page['event_cursor'];documents.update(page['documents'])
                following=page.get('next_after_id')
                if following is None:break
                if not isinstance(following,str) or following<=after:raise RuntimeError('Invalid presentation page cursor')
                after=following
            if stopped():raise RuntimeError('Presentation read cancelled')
            state=request('presentation.metadata',**scope,expected_cursor=cursor) if metadata else page
            return {**state,'documents':documents,'event_cursor':cursor}
        except RuntimeError as exc:
            if 'resync_required' not in str(exc) or attempt==2:raise


class Cache:
    """Refresh only invalidated documents; publish a cache only after consistency checks."""
    def __init__(self):
        self.state=None
        self.scope=None

    def read(self,request,activity=None,metadata=True,stopped=lambda:False):
        scope=None if activity is None else str(activity)
        fields={} if scope is None else {'activity_id':scope}
        if self.state is None or self.scope!=scope:
            state=read(request,scope,metadata,stopped)
            self.state=state;self.scope=scope
            return state
        for attempt in range(3):
            try:
                documents=dict(self.state['documents']);after=self.state['event_cursor'];target=None;changed={}
                while True:
                    if stopped():raise RuntimeError('Presentation read cancelled')
                    query={'after_cursor':after,'limit':64}
                    if target is not None:query['expected_cursor']=target
                    page=request('presentation.changes',**query)
                    latest=page.get('latest_cursor')
                    if type(latest) is not int or latest<after:raise RuntimeError('Invalid change journal cursor')
                    if target is not None and target!=latest:raise RuntimeError('resync_required')
                    target=latest;events=page.get('events')
                    if not isinstance(events,list):raise RuntimeError('Invalid change journal page')
                    for event in events:
                        cursor=event.get('event_cursor');revisions=event.get('revisions')
                        if type(cursor) is not int or not after<cursor<=latest:raise RuntimeError('Invalid change journal order')
                        if not isinstance(revisions,dict) or any(v is not None and (type(v) is not int or v<0) for v in revisions.values()):raise RuntimeError('Invalid change revisions')
                        changed.update(revisions);after=cursor
                    if type(page.get('next_cursor')) is not int or page['next_cursor']!=after:raise RuntimeError('Invalid change journal continuation')
                    if page.get('has_more') is False and after==latest:break
                    if page.get('has_more') is not True or not events or after>=latest:raise RuntimeError('Invalid change journal continuation')
                for ident,revision in changed.items():
                    if stopped():raise RuntimeError('Presentation read cancelled')
                    if revision is None:documents.pop(ident,None);continue
                    try:documents[ident]=request('presentation.get',document_id=ident,expected_cursor=target,**fields)
                    except RuntimeError as exc:
                        if 'missing_reference' not in str(exc):raise
                        documents.pop(ident,None)
                if stopped():raise RuntimeError('Presentation read cancelled')
                if metadata:
                    state=request('presentation.metadata',expected_cursor=target,**fields)
                    if state.get('event_cursor')!=target:raise RuntimeError('resync_required')
                else:
                    guard=request('presentation.changes',after_cursor=target,expected_cursor=target)
                    if guard.get('latest_cursor')!=target or guard.get('events')!=[]:raise RuntimeError('resync_required')
                    state={'event_cursor':target}
                state={**state,'documents':documents};self.state=state
                return state
            except RuntimeError as exc:
                if 'resync_required' not in str(exc):raise
                if attempt<2:continue
                state=read(request,scope,metadata,stopped)
                self.state=state
                return state
