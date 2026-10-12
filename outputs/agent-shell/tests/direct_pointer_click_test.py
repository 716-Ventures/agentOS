# SPDX-License-Identifier: Apache-2.0
"""Fast motion acknowledgement must not collapse adjacent kernel clicks."""
import unittest
from unittest.mock import patch
import direct_input_probe


class PointerClickTest(unittest.TestCase):
    def test_adjacent_clicks_remain_separate_without_replaying_either_click(self):
        device=direct_input_probe.Device.__new__(direct_input_probe.Device)
        device.motion_ready=lambda *_:None
        device.last_pointer_release=None
        clock=[10.0];buttons=[]
        device.event=lambda kind,code,value:buttons.append((clock[0],value)) if kind==1 else None
        def sleep(seconds):clock[0]+=seconds
        with patch.object(direct_input_probe.time,'monotonic',side_effect=lambda:clock[0]), patch.object(direct_input_probe.time,'sleep',side_effect=sleep):
            device.click(10,10,1280,800)
            device.click(20,20,1280,800)
        self.assertEqual([value for _,value in buttons],[1,0,1,0])
        self.assertGreaterEqual(buttons[2][0]-buttons[1][0],.0399)
        self.assertEqual(device.last_click,{'x':20,'y':20,'button':272})

    def test_motion_wait_already_exceeding_debounce_adds_no_extra_wait(self):
        device=direct_input_probe.Device.__new__(direct_input_probe.Device)
        device.motion_ready=lambda *_:None
        device.last_pointer_release=9.9
        device.event=lambda *_:None
        with patch.object(direct_input_probe.time,'monotonic',return_value=10.0), patch.object(direct_input_probe.time,'sleep') as sleep:
            device.click(10,10,1280,800)
        sleep.assert_not_called()


if __name__=='__main__':unittest.main()
