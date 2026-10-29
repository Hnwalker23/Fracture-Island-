import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
class GameTests(unittest.TestCase):
 def setup_game(self):
  r=server.make_room('ABCDEF')
  for i,island in enumerate(('Verdantia','Pyrrhos')):
   p=server.new_player('P'+str(i),'tok'+str(i),i);p['island']=island;r['players'].append(p)
  r['host']=0;server.start(r);return r
 def test_build_and_income(self):
  r=self.setup_game();p=r['players'][0]
  server.act(r,p,{'action':'build','plot':0,'building':'farm'})
  self.assertEqual(p['energy'],4)
  server.phase(r,'reckoning');server.reckon(r)
  self.assertEqual(p['food'],8) # 6+4-2
  self.assertEqual(r['round'],2)
 def test_double_action_rejected(self):
  r=self.setup_game();p=r['players'][0]
  server.act(r,p,{'action':'build','plot':0,'building':'farm'})
  with self.assertRaises(ValueError):server.act(r,p,{'action':'build','plot':1,'building':'farm'})
 def test_core_collapse(self):
  r=self.setup_game();r['core']=2
  server.phase(r,'reckoning');server.reckon(r)
  self.assertEqual(r['phase'],'collapsed')
 def test_council_majority(self):
  r=self.setup_game();p=r['players'][0]
  server.phase(r,'diplomacy');server.act(r,p,{'action':'propose','law':'harvest'});server.select_proposal(r)
  self.assertEqual(r['proposal']['id'],'harvest')
  r['players'][0]['vote']='yes';r['players'][1]['vote']='no';server.council_resolve(r)
  self.assertFalse(r['proposal']['passed'])
 def test_crisis(self):
  r=self.setup_game();r['round']=3;r['crisis_target']=4
  for p in r['players']:p['pledge']=2
  server.resolve_crisis(r)
  self.assertEqual(r['core'],75)
  self.assertEqual(r['players'][0]['contrib'],2)
 def test_unique_island(self):
  r=self.setup_game()
  server.phase(r,'lobby')
  with self.assertRaises(ValueError):server.act(r,r['players'][1],{'action':'choose','island':'Verdantia'})
if __name__=='__main__':unittest.main()
