"""Credential-isolated Jev assessment subprocess for the broker."""
import json
import sys
from common import LIMIT
from providers import config
from jev import evaluate_action
if __name__=='__main__':
    raw=sys.stdin.buffer.read(LIMIT+1)
    if len(raw)>LIMIT:
        result={'status':'unavailable','risk':'uncertain','confidence':0,'reason':'Assessment input exceeded the local message limit.'}
    else:
        action=json.loads(raw)
        result=evaluate_action(action,config())
    print(json.dumps(result))
