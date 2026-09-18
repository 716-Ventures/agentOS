"""Credential-isolated Jev assessment subprocess for the broker."""
import json
import sys
from providers import config
from jev import evaluate_action
if __name__=='__main__':
    action=json.loads(sys.stdin.read(65537))
    print(json.dumps(evaluate_action(action,config())))
