import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/'client/agent_os.py'
spec=importlib.util.spec_from_file_location('client',p);ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)

class Tiling(unittest.TestCase):
    def test_nested_geometry_covers_without_overlap(self):
        a,b,c=ui.leaf(1),ui.leaf(2),ui.leaf(3)
        tree={'axis':'x','ratio':.55,'first':a,'second':{'axis':'y','ratio':.4,'first':b,'second':c}}
        for w,h in ((80,24),(116,34),(180,48)):
            rects=ui.rectangles(tree,0,0,w,h)
            self.assertEqual(len(rects),3)
            covered=set()
            for _,x,y,rw,rh in rects:
                self.assertGreaterEqual(rw,28);self.assertGreaterEqual(rh,7)
                area={(xx,yy) for xx in range(x,x+rw) for yy in range(y,y+rh)}
                self.assertFalse(covered&area);covered |= area
                self.assertLessEqual(x+rw,w);self.assertLessEqual(y+rh,h)

    def test_close_preserves_other_views_and_process_ids(self):
        a,b,c=ui.leaf(10),ui.leaf(20),ui.leaf(30)
        tree={'axis':'x','ratio':.5,'first':a,'second':{'axis':'y','ratio':.5,'first':b,'second':c}}
        result=ui.close_tile(tree,b['id'])
        self.assertEqual([p['job'] for p in ui.leaves(result)],[10,30])
        self.assertTrue(ui.valid_tree(result))

    def test_bad_persisted_layout_rejected(self):
        self.assertFalse(ui.valid_tree({'axis':'x','ratio':0,'first':ui.leaf(),'second':ui.leaf()}))
        self.assertFalse(ui.valid_tree({'id':'a','view':'bad','scroll':0}))
        self.assertTrue(ui.valid_tree(ui.leaf()))

    def test_unicode_display_width(self):
        self.assertEqual(ui.cells('你好a'),5)
        self.assertEqual(ui.clipped('你好a',3),'你')
        for line in ui.wrapped('你好世界 hello\ne\u0301',6):self.assertLessEqual(ui.cells(line),6)

if __name__=='__main__':unittest.main()
