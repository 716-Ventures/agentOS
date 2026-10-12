# SPDX-License-Identifier: Apache-2.0
"""The installed journey must tolerate disappearing AT-SPI children."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class Node:
    def __init__(self, name='', children=(), description='', parent=None):
        self.name, self.children = name, children
        self.description, self.parent = description, parent
        self.childCount = len(children)

    def __getitem__(self, index):
        return self.children[index]

    def getRole(self):
        return 'button'

    def getState(self):
        return SimpleNamespace(contains=lambda state: True)

    def getRoleName(self):
        return 'button'


class InstalledControlSearchTest(unittest.TestCase):
    def search(self, root, wait):
        # Load the real search without starting installed services or requiring
        # Linux AT-SPI/GTK bindings on the host unit-test runner.
        shell = Path(__file__).resolve().parents[1]
        native = shell / 'native-shell' if (shell / 'native-shell').is_dir() else shell.parent / 'native-shell'
        path = native / 'tests/installed_broker.py'
        tree = ast.parse(path.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'button')
        namespace = {'pyatspi': SimpleNamespace(
            Registry=SimpleNamespace(getDesktop=lambda _: root),
            ROLE_PUSH_BUTTON='button', STATE_SENSITIVE='sensitive'),
            'accessibility': SimpleNamespace(wait=wait)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        return namespace['button']

    def test_absent_child_does_not_hide_the_scoped_actionable_button(self):
        wanted = Node('Approve', description='Work broker:7')
        root = Node(children=(None, Node('Approve', description='Work broker:8'), wanted))
        def wait(predicate, _):
            self.assertTrue(predicate())
        self.assertIs(self.search(root, wait)('Approve', 7), wanted)

    def test_absent_child_in_failure_diagnostics_preserves_missing_control_failure(self):
        root = Node(children=(None,))
        def wait(predicate, description):
            self.assertFalse(predicate())
            raise AssertionError(description)
        with self.assertRaisesRegex(AssertionError, 'Actionable installed control missing: Approve'):
            self.search(root, wait)('Approve', 7)


if __name__ == '__main__':
    unittest.main()
