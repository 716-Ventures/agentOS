"""Establish fixture focus across explicitly rejected compositor revisions."""
import json


def focus(request,workspace_id,surface_id,element_id,request_id):
    # Initial placement can advance the workspace between read and apply.
    # Only an explicit stale rejection proves no mutation happened. Transport
    # errors and other rejections escape; an uncertain command is never replayed.
    for attempt in range(8):
        workspace=request({'op':'presentation.snapshot'})['documents'][workspace_id]
        try:
            return request({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
                'request_id':request_id+'-'+str(attempt),'expected_revisions':{workspace_id:workspace['revision']},
                'operations':[{'op':'workspace.edit','workspace_id':workspace_id,
                    'edit':{'kind':'focus','surface_id':surface_id,'element_id':element_id}}]})
        except AssertionError as error:
            response=error.args[0] if error.args else None
            if not isinstance(response,dict) or response.get('ok') is not False:raise
            try:code=json.loads(response.get('error',''))['code']
            except (ValueError,KeyError,TypeError):raise error
            if code!='stale_revision' or attempt==7:raise
