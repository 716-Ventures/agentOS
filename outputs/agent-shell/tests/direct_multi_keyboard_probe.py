# SPDX-License-Identifier: Apache-2.0
"""Owned uinput keyboards: merged modifiers, device loss and OSK isolation."""
import subprocess
import time


def verify(scene, snapshot, keyboard, click, wait):
    from direct_input_probe import Device

    def key(device, pressed):
        device.event(1, 42, int(pressed))
        device.sync()

    def discovered():
        device = Device(True)
        try:
            subprocess.run(['udevadm', 'settle', '--timeout=5'], check=True)
            time.sleep(.5)  # bounded kernel/udev/libinput hotplug discovery
            return device
        except BaseException:
            device.close()
            raise

    def text(value):
        return wait(lambda state: state['text'] == value)

    def held(count):
        wait(lambda _: scene()['keyboard_pressed_count'] == count)

    def rejected(value):
        assert 'Release physical keys' not in snapshot('keyboard-status')['text'], 'Require a fresh keyboard response'
        click('a')
        wait(lambda _: 'Release physical keys' in snapshot('keyboard-status')['text'])
        assert snapshot()['text'] == value, 'On-screen input changed text while another keyboard held Shift'
        assert scene()['keyboard_pressed_count'] == 1

    def ordinary(value):
        held(0)
        click('a')
        text(value + 'a')
        assert 'Release physical keys' not in snapshot('keyboard-status')['text']
        return value + 'a'

    # Clear the preceding single-keyboard rejection with acknowledged input.
    value = ordinary(snapshot()['text'])
    second = discovered()
    try:
        second.chord(48)  # b proves the second kernel device was discovered.
        value += 'b'
        text(value)
        key(keyboard, True)
        held(1)
        key(second, True)
        second.chord(46)  # C acknowledges the second device's held Shift.
        value += 'C'
        text(value)
        key(keyboard, False)
        second.chord(32)  # D must still use the remaining modifier.
        value += 'D'
        text(value)
        held(1)
        rejected(value)
        key(second, False)
        value = ordinary(value)  # Last release restores lowercase input.

        key(keyboard, True)
        held(1)
        key(second, True)
        second.chord(18)
        value += 'E'
        text(value)
        second.close()  # Remove a held device while another owns the same key.
        second = None
        subprocess.run(['udevadm', 'settle', '--timeout=5'], check=True)
        time.sleep(.1)
        keyboard.chord(33)
        value += 'F'
        text(value)
        held(1)
        rejected(value)
        key(keyboard, False)
        value = ordinary(value)

        second = discovered()
        key(second, True)
        second.chord(34)
        value += 'G'
        text(value)
        held(1)
        second.close()  # Removal of the last owner must balance the seat.
        second = None
        value = ordinary(value)
        assert snapshot()['focused'], 'Device removal lost editor focus'
    finally:
        key(keyboard, False)
        if second is not None:
            try:
                key(second, False)
            finally:
                second.close()
    print('PASS: two kernel keyboards retain merged Shift and reject OSK input after partial release/removal; last release/removal restores lowercase, balanced keys and focus', flush=True)
