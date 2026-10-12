# SPDX-License-Identifier: Apache-2.0
"""Observe one consistent mapped identity before post-Undo kernel input."""
import unittest
from unittest.mock import patch
import direct_input_probe


def snapshot(identities, windows):
    return {'shared': {'identities': identities}, 'windows': [{'id': ident} for ident in windows]}


class SurfaceRemapTest(unittest.TestCase):
    def test_waits_for_identity_and_mapped_window_from_the_same_snapshot(self):
        states = iter([snapshot({}, []), snapshot({'new': 'editor'}, []),
                       snapshot({'new': 'editor'}, ['new'])])
        with patch.object(direct_input_probe.time, 'sleep') as sleep:
            self.assertEqual(direct_input_probe.wait_for_mapped_surface(lambda: next(states), 'editor'), 'new')
        self.assertEqual(sleep.call_count, 2)

    def test_old_unmapped_identity_cannot_replace_the_returning_window(self):
        state = snapshot({'old': 'editor', 'new': 'editor', 'other': 'monitor'}, ['new', 'other'])
        self.assertEqual(direct_input_probe.wait_for_mapped_surface(lambda: state, 'editor'), 'new')

    def test_missing_surface_still_fails_with_bounded_diagnostics(self):
        with self.assertRaisesRegex(RuntimeError, 'Native surface did not map:.*editor'):
            direct_input_probe.wait_for_mapped_surface(lambda: snapshot({}, []), 'editor', timeout=0)

    def test_ambiguous_mapped_identity_is_rejected(self):
        state = snapshot({'a': 'editor', 'b': 'editor'}, ['a', 'b'])
        with self.assertRaisesRegex(RuntimeError, 'Ambiguous mapped surface identity'):
            direct_input_probe.wait_for_mapped_surface(lambda: state, 'editor')


if __name__ == '__main__':
    unittest.main()
