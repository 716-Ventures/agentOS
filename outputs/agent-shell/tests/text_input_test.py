import curses
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
from text_input import burst


class Screen:
    def __init__(self, keys): self.keys = list(keys); self.timeouts = []
    def timeout(self, value): self.timeouts.append(value)
    def get_wch(self):
        if not self.keys: raise curses.error()
        return self.keys.pop(0)


class TextInputTest(unittest.TestCase):
    def test_unicode_paste_defers_submit_without_consuming_later_input(self):
        screen = Screen(['日', '本', '語', '\n', 'q'])
        self.assertEqual(burst(screen, 'λ', 4000), ('λ日本語', '\n'))
        self.assertEqual(screen.keys, ['q'])
        self.assertEqual(screen.timeouts, [0, 150])

    def test_burst_and_editor_capacity_are_bounded_and_navigation_is_retained(self):
        screen = Screen(['x'] * 300 + [curses.KEY_LEFT])
        self.assertEqual(burst(screen, 'x', 3), ('xxx', None))
        self.assertEqual(len(screen.keys), 46)
        self.assertEqual(burst(screen, 'x', 0), ('', curses.KEY_LEFT))

    def test_no_ready_input_restores_normal_timeout(self):
        screen = Screen([])
        self.assertEqual(burst(screen, 'a', 10), ('a', None))
        self.assertEqual(screen.timeouts, [0, 150])


if __name__ == '__main__': unittest.main()
