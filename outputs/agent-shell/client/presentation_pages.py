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
