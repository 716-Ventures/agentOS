"""Drain a bounded printable terminal burst without swallowing control keys."""
import curses


def burst(screen, first, capacity, maximum=256):
    text = first[:max(0, capacity)]
    following = None
    screen.timeout(0)
    try:
        for _ in range(maximum - 1):
            try: key = screen.get_wch()
            except curses.error: break
            if not isinstance(key, str) or not key.isprintable():
                following = key
                break
            if len(text) < capacity: text += key
    finally:
        screen.timeout(150)
    return text, following
