import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from install_lizzie_terrain import install
from lizzie_terrain import Board, Mirror, detect_perspective, handler_for


class MirrorTests(unittest.TestCase):
    def command(self, mirror, line, result=''):
        sent=mirror.prepare(line+'\n'); internal_id=sent.split()[0]
        output=mirror.observe(f'={internal_id}'+(' '+result if result else '')+'\n')
        mirror.observe('\n')
        return sent,output

    def analyze(self, mirror, player='b', value=.8):
        sent=mirror.prepare(f'91 kata-analyze {player} 10\n')
        mirror.observe('='+sent.split()[0]+'\n')
        line='info move D4 visits 20 winrate 0.6 ownership '+' '.join([str(value)]*(mirror.board.size**2))+'\n'
        mirror.observe(line)
        return line

    def test_ids_and_ownership_requested_without_breaking_other_args(self):
        mirror=Mirror()
        sent=mirror.prepare('42 kata-analyze w 10 ownership false allow w D4 1\n')
        self.assertIn('ownership true allow w D4 1',sent)
        self.assertEqual(mirror.observe('=1\n'),'=42\n')
        self.assertEqual(mirror.observe('info move D4 visits 1\n'),'info move D4 visits 1\n')
        mirror.observe('\n')
        sent,out=self.command(mirror,'name','KataGo')
        self.assertEqual(out,'= KataGo\n')

    def test_capture_undo_pass_and_failed_command(self):
        m=Mirror();self.command(m,'boardsize 9')
        self.command(m,'set_position w B2 b A2 b C2 b B1')
        before=m.board.stones.copy();self.command(m,'play b B3')
        self.assertEqual(m.board.stones[m.board.index('B2')],0)
        self.command(m,'undo');self.assertEqual(m.board.stones,before)
        self.command(m,'play w pass');self.assertEqual(len(m.board.history),1)
        sent=m.prepare('17 play b A2\n');self.assertEqual(m.observe('?'+sent.split()[0]+' illegal move\n'),'?17 illegal move\n')
        m.observe('\n');self.assertEqual(m.board.stones,before)

    def test_white_perspective_and_stale_reports(self):
        m=Mirror();line=self.analyze(m,'w')
        self.assertEqual(m.snapshot()['ownership'][0],-.8)
        sent=m.prepare('play b D4\n')
        m.observe(line)  # Late old analysis before command acknowledgement.
        self.assertIsNone(m.snapshot()['ownership'])
        m.observe('='+sent.split()[0]+'\n');m.observe('\n')
        self.assertEqual(m.board.stones[m.board.index('D4')],1)
        self.analyze(m,'b');self.assertEqual(m.snapshot()['ownership'][0],.8)
        for perspective,expected in [('BLACK',.8),('WHITE',-.8)]:
            mm=Mirror(perspective);self.analyze(mm,'w');self.assertEqual(mm.snapshot()['ownership'][0],expected)

    def test_setup_handicap_and_generated_moves(self):
        m=Mirror();self.command(m,'fixed_handicap 2','D4 Q16')
        self.assertEqual(m.board.player,2);self.assertEqual(sum(v==1 for v in m.board.stones),2)
        self.command(m,'genmove w','D16');self.assertEqual(m.board.stones[m.board.index('D16')],2)
        self.command(m,'undo');self.assertEqual(m.board.player,2)
        self.command(m,'clear_board');self.assertFalse(any(m.board.stones))
        self.command(m,'loadsgf example.sgf');self.assertFalse(m.synchronized)
        self.analyze(m);self.assertIsNone(m.snapshot()['ownership'])
        self.command(m,'clear_board');self.assertTrue(m.synchronized)

    def test_short_or_nonfinite_ownership_rejected(self):
        m=Mirror();sent=m.prepare('kata-analyze 10\n');m.observe('='+sent.split()[0]+'\n')
        for values in ['.1 .2', ' '.join(['nan']*361)]:
            m.observe('info move D4 visits 1 ownership '+values+'\n')
            self.assertIsNone(m.snapshot()['ownership'])

    def test_read_only_loopback_http(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Mirror()))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}'
            with urllib.request.urlopen(url+'/api/terrain') as response:
                self.assertEqual(json.load(response)['source'],'lizzie-gtp')
            for path in ['/../server.py','/api/library']:
                with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(url+path)
                self.assertEqual(error.exception.code,404)
            request=urllib.request.Request(url+'/api/terrain',headers={'Host':'evil.example'})
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url+'/api/terrain',data=b'{}'))
            self.assertEqual(error.exception.code,501)
        finally: server.shutdown();server.server_close();worker.join()

    def test_install_is_reversible_idempotent_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'config.txt'
            source={'name':'original','command':'"C:\\Kata Go\\katago.exe" gtp -config local.cfg','isDefault':True}
            original={'leelaz':{'engine-settings-list':[source]},'ui':{'default-engine':0}}
            p.write_text(json.dumps(original),encoding='utf-8')
            backup,index=install(p,make_default=True)
            self.assertEqual(json.loads(backup.read_text('utf-8')),original)
            d=json.loads(p.read_text('utf-8'));self.assertEqual(index,1)
            self.assertEqual(d['leelaz']['engine-settings-list'][0]['command'],source['command'])
            self.assertEqual(d['ui']['default-engine'],1)
            self.assertIn(' -- '+source['command'],d['leelaz']['engine-settings-list'][1]['command'])
            install(p);self.assertEqual(len(json.loads(p.read_text('utf-8'))['leelaz']['engine-settings-list']),2)
            with self.assertRaises(ValueError):install(p,engine_index=1)

    def test_configured_perspective(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'gtp.cfg';p.write_text('# reportAnalysisWinratesAs = WHITE\nreportAnalysisWinratesAs = BLACK\n')
            self.assertEqual(detect_perspective(['katago','gtp','-config',str(p)]),'BLACK')
            self.assertEqual(detect_perspective(['katago','gtp','-config',str(p),'-override-config','reportAnalysisWinratesAs=WHITE']),'WHITE')


if __name__=='__main__': unittest.main()
