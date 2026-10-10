"""Complete broker metadata pages without collecting output, stdin or private assessment evidence."""
import re
def read(request,activity=None,stopped=lambda:False,recent=False):
    for attempt in range(3):
        try:
            jobs=[];before=None;revision=None
            while True:
                if stopped():raise RuntimeError('Broker read cancelled')
                fields={'before':before,'limit':32,'recent_only':recent}
                if activity is not None:fields['activity']=int(activity)
                if revision is not None:fields['expected_revision']=revision
                page=request('list.page',**fields)
                observed=page.get('revision')
                if not isinstance(observed,str) or not observed:raise RuntimeError('Invalid broker revision')
                if revision is not None and observed!=revision:raise RuntimeError('resync_required')
                revision=observed;rows=page.get('jobs')
                if not isinstance(rows,list):raise RuntimeError('Invalid broker metadata page')
                previous=tuple(before) if before is not None else None
                for row in rows:
                    if (not isinstance(row,dict) or type(row.get('created_at')) not in (int,float) or not 0<=row['created_at']<=2**53
                            or not isinstance(row.get('id'),str) or not re.fullmatch('[0-9a-f]{32}',row['id'])):raise RuntimeError('Invalid broker row')
                    key=(row['created_at'],row['id'])
                    if previous is not None and key>=previous:raise RuntimeError('Invalid broker row cursor')
                    previous=key
                jobs.extend(rows);following=page.get('next_before')
                if following is None:return jobs
                if not rows or not isinstance(following,list) or len(following)!=2 or tuple(following)!=previous:raise RuntimeError('Invalid broker page cursor')
                before=following
        except (RuntimeError,ValueError) as exc:
            if 'resync_required' not in str(exc) or attempt==2:raise
