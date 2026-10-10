"""Validate immutable input context separately from the person's submitted instruction."""
import json
import math
import re
import time


def validate(value,activity):
    if not isinstance(value,dict) or set(value)-{'input_id','captured_at','modality','activity_id','surface_id','layout_revision','job_ref','selection','expected_generation','selection_kind','surface_title'}:
        raise ValueError('Invalid input context fields')
    if value.get('activity_id')!=activity:raise ValueError('Voice input belongs to a different activity')
    if not isinstance(value.get('input_id'),str) or not re.fullmatch(r'[a-f0-9]{32}',value['input_id']):raise ValueError('Invalid input identity')
    captured=value.get('captured_at')
    if type(captured) not in (int,float) or not math.isfinite(captured) or captured<=0 or captured>time.time()+30:raise ValueError('Invalid input timestamp')
    if value.get('modality')!='voice':raise ValueError('Invalid input modality')
    for key in ('layout_revision','expected_generation'):
        if type(value.get(key)) is not int or value[key]<0:raise ValueError('Missing context revision/generation')
    if not isinstance(value.get('surface_id'),str) or not 1<=len(value['surface_id'])<=128:raise ValueError('Invalid input surface')
    ref=value.get('job_ref')
    if ref is not None and not ((type(ref) is int and ref>0) or (isinstance(ref,str) and re.fullmatch(r'broker:[a-f0-9]{32}',ref))):raise ValueError('Invalid input job reference')
    if value.get('selection_kind')!='focused_output' or not isinstance(value.get('surface_title'),str) or len(value['surface_title'])>200:raise ValueError('Invalid referenced output')
    selection=value.get('selection','')
    if not isinstance(selection,str) or len(selection)>12000:raise ValueError('Input selection exceeds its limit')
    if len(json.dumps(value))>64000:raise ValueError('Input context exceeds its limit')
    return dict(value)
