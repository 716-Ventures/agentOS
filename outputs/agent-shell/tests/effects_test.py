import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
from effects import assess
class Effects(unittest.TestCase):
 def test_unfamiliar_commands_go_to_runtime_assessment(self):
  for argv in (['/usr/bin/python3','-m','http.server','9123'],['/opt/project/node_modules/.bin/next','dev'],['/bin/sh','-c','npm run build > build.log'],['/usr/bin/apt-get','install','vlc']):
   self.assertEqual(assess(argv,'workspace')['decision'],'inspect')
 def test_hazards_require_confirmation(self):
  for argv in (['/bin/rm','-rf','project'],['/bin/sh','-c','echo $(rm -rf project)'],['/usr/bin/python3','-c','import shutil;shutil.rmtree("project")'],['/usr/bin/systemctl','stop','ssh.service']):
   self.assertEqual(assess(argv,'system')['decision'],'approve')
 def test_install_retains_no_removal_guard(self):
  self.assertIn('--no-remove',assess(['/usr/bin/apt-get','install','-y','git'],'system')['argv'])
if __name__=='__main__':unittest.main()
