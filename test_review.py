import base64, copy, json, os, tempfile, unittest, urllib.request
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import Mock
import server

def fresh(**kw):
    return dict(size=9,komi=7.5,rules='chinese',moves=[],initialStones=[],initialPlayer='B',analysis={})|kw

class ReviewTests(unittest.TestCase):
    def test_capture(self):
        g=server.replay(fresh(moves=[['B','A2'],['W','A1'],['B','B1']]))
        self.assertEqual(g['positions'][-1][8*9],0)
        self.assertEqual(g['captures'][-1],[1,0])
    def test_occupied_and_suicide(self):
        with self.assertRaises(ValueError):server.replay(fresh(moves=[['B','A1'],['W','A1']]))
        with self.assertRaises(ValueError):server.replay(fresh(initialStones=[['B','A2'],['B','B1']],moves=[['W','A1']]))
    def test_ko(self):
        # White B2 is in atari, black B3 takes; immediate B2 recapture is illegal.
        setup=[['W','B2'],['W','A3'],['W','C3'],['W','B4'],['B','A2'],['B','C2'],['B','B1']]
        server.replay(fresh(initialStones=setup,moves=[['B','B3']]))
        for rules in ['chinese','japanese']:
            with self.assertRaises(ValueError):server.replay(fresh(rules=rules,initialStones=setup,moves=[['B','B3'],['W','B2']]))
    def test_handicap_encoding_and_mainline(self):
        raw='(;FF[4]CA[UTF-8]SZ[19]HA[2]AB[dd][pp]PB[张三]PW[李四];W[qd](;B[dc])(;B[cc]))'.encode()
        g=server.parse_sgf(raw,'让子测试')
        self.assertEqual(g['initialPlayer'],'W');self.assertEqual(g['black'],'张三')
        self.assertEqual(g['moves'],[['W','R16'],['B','D17']]);self.assertEqual(len(g['initialStones']),2)
    def test_pass_and_coordinate_orientation(self):
        g=server.parse_sgf(b'(;SZ[9];B[aa];W[];B[ii])','test')
        self.assertEqual(g['moves'],[['B','A9'],['W','pass'],['B','J1']])
        self.assertEqual(g['positions'][-1][0],1);self.assertEqual(g['positions'][-1][-1],1)
    def test_fox_komi_duplicate_ap_and_missing_encoding(self):
        raw='(;FF[4]SZ[19]AP[GNU Go:3.8]AP[foxwq]PB[测试黑方]PW[TestWhite]KM[375]RU[Chinese];B[pd])'.encode('utf8')
        g=server.parse_sgf(raw,'野狐实战')
        self.assertEqual(g['komi'],7.5);self.assertEqual(g['black'],'测试黑方')
        self.assertEqual(g['moves'],[['B','Q16']]);self.assertEqual(g['parserVersion'],2)
        old=g|{'parserVersion':0,'komi':375,'black':'乱码','analysis':{'0':{'wrong':True}}}
        fixed=server.normalize_saved(old)
        self.assertEqual(fixed['analysis'],{});self.assertEqual(fixed['komi'],7.5)
        self.assertEqual(fixed['black'],'测试黑方')
    def test_gb_chinese_and_declared_latin(self):
        g=server.parse_sgf('(;SZ[9]PB[张三]KM[7.5])'.encode('gb18030'),'test')
        self.assertEqual(g['black'],'张三')
        g=server.parse_sgf('(;CA[ISO-8859-1]SZ[9]PB[René]KM[7.5])'.encode('latin1'),'test')
        self.assertEqual(g['black'],'René')
    def test_no_conversion_for_standard_komi(self):
        for km in [0,6.5,7.5,375]:
            g=server.parse_sgf(f'(;CA[UTF-8]SZ[9]KM[{km}])'.encode(),'test')
            self.assertEqual(g['komi'],km)
    def test_saved_text_repair_preserves_valid_analysis(self):
        raw='(;SZ[9]PB[张三]KM[7.5])'.encode()
        g=server.parse_sgf(raw,'test')|{'parserVersion':0,'analysis':{'0':{'valid':True}}}
        self.assertEqual(server.normalize_saved(g)['analysis'],{'0':{'valid':True}})
    def test_continuous_search_does_not_stop_at_selected_batch_visits(self):
        engine=server.Engine();requests=[]
        engine.start=lambda:None
        engine.send=requests.append
        engine.analyze(fresh(),[0],400,continuous=True)
        self.assertEqual(requests[-1]['maxVisits'],20000)
        self.assertEqual(requests[-1]['reportDuringSearchEvery'],0.5)
        engine.analyze(fresh(),[0],400)
        self.assertEqual(requests[-1]['maxVisits'],400)
    def test_stale_browser_save_preserves_finished_record(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'LIB',Path(directory)):
            g=fresh(id='a'*32,analysis={'0':{'rootInfo':{'visits':1600}}})
            server.save_game(copy.deepcopy(g))
            g['analysis']={'0':{'rootInfo':{'visits':400}}}
            server.save_game(copy.deepcopy(g))
            stored=json.loads((Path(directory)/('a'*32+'.json')).read_text('utf8'))
            self.assertEqual(stored['analysis']['0']['rootInfo']['visits'],1600)
            g['komi']=6.5;g['analysis']={}
            server.save_game(g)
            stored=json.loads((Path(directory)/('a'*32+'.json')).read_text('utf8'))
            self.assertEqual(stored['analysis'],{})
    def test_stability_requires_window_and_enough_search(self):
        def report(v,w=.37,s=-1,m='Q16'):
            return dict(rootInfo=dict(visits=v,winrate=w,scoreLead=s),moveInfos=[dict(move=m,order=0)])
        job={}
        for t in range(15):self.assertEqual(server.convergence_reason(job,report(2000+100*t),now=t),'')
        self.assertIn('稳定',server.convergence_reason(job,report(3500),now=15))
        low={}
        for t in range(30):self.assertEqual(server.convergence_reason(low,report(10+t),now=t),'')
        duplicate={}
        self.assertEqual(server.convergence_reason(duplicate,report(2500),now=0),'')
        self.assertEqual(server.convergence_reason(duplicate,report(2500),now=20),'')
    def test_unstable_best_move_or_evaluation_keeps_searching(self):
        for kind in ('move','winrate','score'):
            job={}
            for t in range(16):
                report=dict(rootInfo=dict(visits=2000+t*100,winrate=.37+(0.02 if kind=='winrate' and t==8 else 0),scoreLead=1+(1 if kind=='score' and t==8 else 0)),moveInfos=[dict(order=0,move='D4' if kind=='move' and t==8 else 'Q16')])
                self.assertEqual(server.convergence_reason(job,report,now=t),'')
    def test_search_and_time_caps(self):
        report=dict(rootInfo=dict(visits=20000),moveInfos=[])
        self.assertIn('20,000',server.convergence_reason({},report,now=0))
        self.assertIn('60 秒',server.convergence_reason({'started':0},dict(rootInfo=dict(visits=1)),now=60))
    def test_monitor_stops_even_if_engine_stops_reporting(self):
        engine=server.Engine();sent=[];engine.send=sent.append
        engine.jobs['test']=dict(continuous=True,done=False,started=server.time.monotonic()-61)
        process=SimpleNamespace(poll=Mock(side_effect=[None,0]))
        with patch.object(server.time,'sleep'):engine.monitor(process)
        self.assertTrue(engine.jobs['test']['done'])
        self.assertIn('60 秒',engine.jobs['test']['stopReason'])
        self.assertEqual(sent[0]['terminateId'],'test')
    @unittest.skipUnless(os.environ.get('YIJING_INTEGRATION')=='1','optional live engine integration')
    def test_http_status_and_validation(self):
        d=json.load(urllib.request.urlopen('http://127.0.0.1:18765/api/status'))
        self.assertEqual(d['app'],'yijing');self.assertTrue(d['ready'])

if __name__=='__main__':unittest.main()
