"""Compare packaged capabilities with the built core without starting services."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    state=Path(tmp)/'state';endpoint=Path(tmp)/'runtime.sock'
    catalog=json.loads(subprocess.check_output([str(root/'target/release/agent-os-core'),'--catalog'],env={**os.environ,'AGENT_OS_STATE':str(state),'AGENT_OS_SOCKET':str(endpoint)},timeout=10))
    assert not state.exists() and not endpoint.exists(), 'Catalog inspection must not initialize state or sockets'
contract=json.loads((root/'release-contract.json').read_text())
assert sorted(contract['components'])==sorted(catalog['components']), 'Packaged capabilities differ from the built validator'
print('PASS: release capabilities exactly match the side-effect-free core catalog')
