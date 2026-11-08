"""Local, read-only 3D companion for KataGo GTP clients (Lizzie / LizzieYzy).

Run as the GUI's engine command. Stdout is exclusively GTP; diagnostics use stderr.
Only successful engine responses change the mirrored board. Epochs reject analysis
that arrives after a navigation command but before KataGo has processed it.
"""
import argparse
import copy
import json
import math
import re
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
COLS = 'ABCDEFGHJKLMNOPQRST'
ASSETS = {'/terrain.js', '/terrain-companion.js', '/style.css',
          '/vendor/three.module.js', '/vendor/OrbitControls.js'}
MUTATIONS = {'boardsize', 'rectangular_boardsize', 'clear_board', 'play', 'undo',
             'set_position', 'fixed_handicap', 'place_free_handicap',
             'set_free_handicap', 'loadsgf', 'genmove', 'kata-genmove_analyze',
             'lz-genmove_analyze', 'genmove_analyze', 'komi', 'kata-set-rules',
             'kata-set-rule', 'kgs-rules'}
ANALYSIS = {'kata-analyze', 'analyze', 'kata-genmove_analyze', 'genmove_analyze'}


def color(value):
    value = value.lower()
    if value in ('b', 'black'): return 1
    if value in ('w', 'white'): return 2
    raise ValueError('invalid player')


class Board:
    def __init__(self, size=19):
        self.size = size
        self.stones = [0] * (size * size)
        self.history = []
        self.player = 1

    def index(self, vertex):
        vertex = vertex.upper()
        if vertex == 'PASS': return None
        if not re.fullmatch(r'[A-HJ-T][1-9][0-9]?', vertex):
            raise ValueError('unsupported vertex')
        x, y = COLS.index(vertex[0]), self.size - int(vertex[1:])
        if not (0 <= x < self.size and 0 <= y < self.size):
            raise ValueError('vertex outside board')
        return y * self.size + x

    def neighbors(self, i):
        n = self.size; x, y = i % n, i // n
        return [yy*n+xx for xx, yy in ((x-1,y),(x+1,y),(x,y-1),(x,y+1))
                if 0 <= xx < n and 0 <= yy < n]

    def group(self, i):
        stones, todo, liberties = {i}, [i], set()
        while todo:
            for j in self.neighbors(todo.pop()):
                if not self.stones[j]: liberties.add(j)
                elif self.stones[j] == self.stones[i] and j not in stones:
                    stones.add(j); todo.append(j)
        return stones, liberties

    def play(self, player, vertex):
        if vertex.lower() == 'resign': return
        i = self.index(vertex)
        if i is not None and self.stones[i]: raise ValueError('occupied vertex')
        self.history.append((self.stones.copy(), self.player))
        if i is not None:
            self.stones[i] = player
            for j in self.neighbors(i):
                if self.stones[j] and self.stones[j] != player:
                    group, liberties = self.group(j)
                    if not liberties:
                        for k in group: self.stones[k] = 0
            # Mirror legal multi-stone suicide too, when enabled in KataGo rules.
            group, liberties = self.group(i)
            if not liberties:
                for k in group: self.stones[k] = 0
        self.player = 3 - player

    def setup(self, pairs, player=1):
        self.stones = [0] * (self.size * self.size); self.history = []
        for player_value, vertex in pairs:
            i = self.index(vertex)
            if i is None or self.stones[i]: raise ValueError('invalid setup')
            self.stones[i] = player_value
        self.player = player


@dataclass
class Pending:
    original_id: str
    name: str
    args: list
    epoch: int
    player: int = 1


class Mirror:
    def __init__(self, perspective='SIDETOMOVE'):
        self.lock = threading.RLock()
        self.board = Board(); self.perspective = perspective
        self.epoch = 0; self.serial = 0; self.revision = 0
        self.pending = {}; self.response = None; self.success = False; self.body = []
        self.ownership = None; self.visits = 0; self.synchronized = True
        self.message = '在 Lizzie 中开始 KataGo 分析，地形将自动同步。'
        self.connected = True

    def prepare(self, line):
        with self.lock:
            tokens = line.split('#', 1)[0].split()
            if not tokens: return line
            original_id = tokens.pop(0) if tokens[0].isdigit() else ''
            if not tokens: return line
            name, args = tokens[0].lower(), tokens[1:]
            if name in MUTATIONS or name in ANALYSIS:
                self.epoch += 1; self.ownership = None; self.visits = 0
                self.message = '等待当前局面分析…'; self.revision += 1
            if name in ANALYSIS:
                if 'ownership' in args:
                    i = args.index('ownership')
                    if i+1 < len(args): args[i+1] = 'true'
                    else: args.append('true')
                else: args.extend(['ownership', 'true'])
            self.serial += 1
            self.pending[str(self.serial)] = Pending(original_id, name, args, self.epoch)
            return f'{self.serial} {name}' + (' ' + ' '.join(args) if args else '') + '\n'

    def finish(self):
        pending = self.response
        if pending and self.success and pending.name in MUTATIONS:
            try:
                # Apply transactionally; failed mirroring must never corrupt later snapshots.
                board = copy.deepcopy(self.board)
                self.apply(board, pending, '\n'.join(self.body))
                self.board = board
                if pending.name in ('boardsize', 'rectangular_boardsize', 'clear_board', 'set_position',
                                    'fixed_handicap', 'place_free_handicap', 'set_free_handicap'):
                    self.synchronized = True
            except (ValueError, IndexError) as exc:
                self.synchronized = False; self.ownership = None
                self.message = f'此局面无法同步：{exc}。请在 Lizzie 重新打开棋谱以同步。'
            self.revision += 1
        self.response = None; self.body = []

    def apply(self, board, pending, payload):
        name, args = pending.name, pending.args
        if name in ('boardsize', 'rectangular_boardsize'):
            n = int(args[0])
            if n not in (9,13,19) or (len(args)>1 and int(args[1])!=n):
                raise ValueError('3D 视图支持 9、13、19 路正方形棋盘')
            board.__init__(n)
        elif name == 'clear_board': board.__init__(board.size)
        elif name == 'play': board.play(color(args[0]), args[1])
        elif name == 'undo':
            if not board.history: raise ValueError('无可同步的上一手')
            board.stones, board.player = board.history.pop()
        elif name == 'set_position':
            if len(args)%2: raise ValueError('invalid setup')
            board.setup([(color(args[i]), args[i+1]) for i in range(0,len(args),2)])
        elif name in ('fixed_handicap', 'place_free_handicap', 'set_free_handicap'):
            vertices = args if name == 'set_free_handicap' else payload.split()
            board.setup([(1, vertex) for vertex in vertices], player=2)
        elif name in ('genmove', 'kata-genmove_analyze', 'lz-genmove_analyze', 'genmove_analyze'):
            vertex = payload.splitlines()[-1].split()[-1]
            board.play(color(args[0]), vertex)
        elif name == 'loadsgf':
            # GUIs normally replay via clear_board/play; direct engine-side SGF
            # loading has version-dependent move-number semantics. Fail visibly.
            raise ValueError('暂不支持引擎直接 loadsgf，请由 GUI 导入棋谱')

    def observe(self, line):
        with self.lock:
            header = re.match(r'^([=?])(\d+)(?:\s(.*))?$', line.rstrip('\r\n'))
            if header:
                self.finish()
                symbol, internal_id, payload = header.groups(); payload = payload or ''
                self.response = self.pending.pop(internal_id, None)
                self.success = symbol == '='; self.body = [payload] if payload else []
                if self.response:
                    args = self.response.args
                    self.response.player = color(args[0]) if args and args[0].lower() in ('b','w','black','white') else self.board.player
                    return symbol + self.response.original_id + (' ' + payload if payload else '') + '\n'
                return line
            if not line.strip(): self.finish()
            elif line.startswith('info '): self.analysis(line)
            elif self.response: self.body.append(line.strip())
            return line

    def analysis(self, line):
        pending = self.response
        if not pending or pending.name not in ANALYSIS or pending.epoch != self.epoch or not self.synchronized:
            return
        tokens = line.split(); count = self.board.size**2
        if 'ownership' not in tokens: return
        i = tokens.index('ownership') + 1
        try:
            values = [float(v) for v in tokens[i:i+count]]
            if len(values)!=count or any(not math.isfinite(v) or abs(v)>1 for v in values): return
            sign = 1 if self.perspective=='BLACK' or (self.perspective=='SIDETOMOVE' and pending.player==1) else -1
            self.ownership = [round(v*sign,6) for v in values]
            root = re.search(r'\brootInfo\s+visits\s+(\d+)', line)
            self.visits = int(root[1]) if root else sum(int(v) for v in re.findall(r'\binfo move \S+ visits (\d+)',line))
            self.message = ''; self.revision += 1
        except ValueError: return

    def snapshot(self):
        with self.lock:
            return dict(source='lizzie-gtp',revision=self.revision,connected=self.connected,
                        size=self.board.size,stones=self.board.stones.copy(),turn=len(self.board.history),
                        ownership=self.ownership.copy() if self.ownership is not None else None,
                        visits=self.visits,message=self.message,synchronized=self.synchronized)


def handler_for(mirror):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            port = self.server.server_port
            if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                return self.send_error(403)
            path = urlparse(self.path).path
            if path == '/api/terrain':
                raw = json.dumps(mirror.snapshot(),ensure_ascii=False).encode('utf-8'); content_type='application/json; charset=utf-8'
            elif path == '/' or path in ASSETS:
                target = ROOT/'web'/('terrain.html' if path=='/' else path[1:])
                raw = target.read_bytes()
                content_type={'.js':'text/javascript; charset=utf-8','.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8'}[target.suffix]
            else: return self.send_error(404)
            self.send_response(200); self.send_header('Content-Type',content_type)
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            try: self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError): pass
    return Handler


def detect_perspective(command):
    value = 'SIDETOMOVE'
    for i, argument in enumerate(command[:-1]):
        if argument in ('-config','--config'):
            text = Path(command[i+1]).read_text(encoding='utf-8')
            found = re.findall(r'^\s*reportAnalysisWinratesAs\s*=\s*(BLACK|WHITE|SIDETOMOVE)\b',text,re.M|re.I)
            if found: value = found[-1].upper()
        elif argument in ('-override-config','--override-config'):
            found = re.search(r'\breportAnalysisWinratesAs=(BLACK|WHITE|SIDETOMOVE)\b',command[i+1],re.I)
            if found: value = found[1].upper()
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=18769)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--perspective',choices=['auto','BLACK','WHITE','SIDETOMOVE'],default='auto')
    parser.add_argument('engine',nargs=argparse.REMAINDER)
    args=parser.parse_args();command=args.engine
    if command[:1]==['--']: command=command[1:]
    if not command: parser.error('Supply the existing KataGo gtp command after --')
    mirror=Mirror(detect_perspective(command) if args.perspective=='auto' else args.perspective)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(mirror))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    proc=None
    try:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                              stderr=sys.stderr,text=True,encoding='utf-8',errors='replace',bufsize=1,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        url=f'http://127.0.0.1:{server.server_port}/'
        print(f'Yijing 3D companion: {url}',file=sys.stderr,flush=True)
        if not args.no_browser: threading.Thread(target=webbrowser.open,args=(url,),daemon=True).start()
        def input_loop():
            try:
                for line in sys.stdin:
                    proc.stdin.write(mirror.prepare(line));proc.stdin.flush()
                proc.stdin.close()
            except (BrokenPipeError,OSError,ValueError): pass
        threading.Thread(target=input_loop,daemon=True).start()
        for line in proc.stdout:
            sys.stdout.write(mirror.observe(line));sys.stdout.flush()
        return proc.wait()
    finally:
        with mirror.lock: mirror.connected=False;mirror.revision+=1
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill();proc.wait()
        server.shutdown();server.server_close()


if __name__=='__main__':
    try: sys.exit(main())
    except (OSError,ValueError) as exc:
        print(f'Yijing 3D companion: {exc}',file=sys.stderr);sys.exit(1)
