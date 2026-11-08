"""弈镜：本地 KataGo 复盘服务。仅监听回环地址。"""
import atexit, base64, json, math, os, re, subprocess, threading, time, uuid
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from sgfmill import sgf

ROOT = Path(__file__).resolve().parent
PORT=int(os.environ.get('YIJING_PORT','18765'))
ENGINE_PATH=Path(os.environ.get('KATAGO_PATH',str(ROOT/'engine'/('katago.exe' if os.name=='nt' else 'katago')))).resolve()
MODEL_PATH=Path(os.environ.get('KATAGO_MODEL',str(ROOT/'engine/model.bin.gz'))).resolve()
CONFIG_PATH=Path(os.environ.get('KATAGO_CONFIG',str(ROOT/'engine/local.cfg'))).resolve()
LIB = ROOT / 'library'
LIB.mkdir(exist_ok=True)
LIB_LOCK=threading.RLock()
COLS = 'ABCDEFGHJKLMNOPQRST'
AUTO_LIMITS=dict(maxVisits=20000,maxSeconds=60,minVisits=2000,stableSeconds=15,winrateRange=0.005,scoreRange=0.3)

def convergence_reason(job,result,now=None):
    """Use distinct search reports; repeated HTTP polls cannot count as stability."""
    now=time.monotonic() if now is None else now
    root=result.get('rootInfo',{});visits=root.get('visits',0)
    if job.get('started') is None:job['started']=now
    if visits>=AUTO_LIMITS['maxVisits']:return '已达到 20,000 次搜索上限'
    if now-job['started']>=AUTO_LIMITS['maxSeconds']:return '已达到 60 秒分析时限'
    if visits<=job.get('lastVisits',-1):return ''
    job['lastVisits']=visits
    moves=result.get('moveInfos',[])
    if not moves:return ''
    best=min(moves,key=lambda m:m.get('order',0))['move']
    samples=job.setdefault('samples',[])
    samples.append((now,visits,root['winrate'],root['scoreLead'],best))
    cutoff=now-AUTO_LIMITS['stableSeconds']
    while len(samples)>1 and samples[1][0]<=cutoff:samples.pop(0)
    if len(samples)<2 or samples[0][0]>cutoff or samples[0][1]<AUTO_LIMITS['minVisits']:return ''
    if len({s[4] for s in samples})!=1:return ''
    if max(s[2] for s in samples)-min(s[2] for s in samples)>AUTO_LIMITS['winrateRange']+1e-9:return ''
    if max(s[3] for s in samples)-min(s[3] for s in samples)>AUTO_LIMITS['scoreRange']+1e-9:return ''
    return '推荐点与局面评价已稳定 15 秒，自动暂停'

def xy(move, n):
    if move.lower() == 'pass': return None
    if not re.fullmatch(r'[A-HJ-T][1-9][0-9]?', move): raise ValueError('无效坐标')
    x, y = COLS.index(move[0]), n-int(move[1:])
    if not (0 <= x < n and 0 <= y < n): raise ValueError('落点超出棋盘')
    return x,y

def coord(p,n):
    return 'pass' if p is None else COLS[p[1]]+str(p[0]+1)

def replay(g):
    komi=float(g.get('komi',7.5))
    if not math.isfinite(komi) or not -400<=komi<=400 or komi*2!=int(komi*2):raise ValueError('贴目必须是 -400 到 400 之间的整数或半整数')
    n = int(g.get('size',19))
    if n not in (9,13,19): raise ValueError('支持 9、13、19 路棋盘')
    b = [0]*(n*n)
    def neighbors(i):
        x,y=i%n,i//n
        return [yy*n+xx for xx,yy in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)) if 0<=xx<n and 0<=yy<n]
    def group(i):
        seen={i}; todo=[i]; libs=set()
        while todo:
            for j in neighbors(todo.pop()):
                if not b[j]: libs.add(j)
                elif b[j]==b[i] and j not in seen: seen.add(j);todo.append(j)
        return seen,libs
    for c,m in g.get('initialStones',[]):
        x,y=xy(m,n);i=y*n+x
        if b[i]:raise ValueError('初始棋子重叠')
        b[i]=1 if c=='B' else 2
    snaps=[b.copy()]; captures=[[0,0]]; cap=[0,0]; hashes=[tuple(b)]
    moves=g.get('moves',[])
    if len(moves)>1200:raise ValueError('棋谱超过 1200 手')
    for turn,(c,m) in enumerate(moves):
        if c not in ('B','W'):raise ValueError('无效棋色')
        p=xy(m,n)
        if p is not None:
            x,y=p;i=y*n+x;v=1 if c=='B' else 2
            if b[i]:raise ValueError(f'第 {turn+1} 手落在已有棋子上')
            b[i]=v
            for j in neighbors(i):
                if b[j] and b[j]!=v:
                    stones,libs=group(j)
                    if not libs:
                        cap[v-1]+=len(stones)
                        for k in stones:b[k]=0
            if not group(i)[1]:raise ValueError(f'第 {turn+1} 手为禁入点')
            h=tuple(b)
            forbidden=hashes[-2:-1] if g.get('rules')=='japanese' else hashes
            if h in forbidden:raise ValueError('违反劫争或全局同形规则')
        hashes.append(tuple(b));snaps.append(b.copy());captures.append(cap.copy())
    g['size']=n;g['positions']=snaps;g['captures']=captures
    return g

def parse_sgf(raw, name):
    s=sgf.Sgf_game.from_bytes(raw);r=s.get_root();notes=[]
    # SGF defaults to Latin-1, but Fox omits CA even when names are UTF-8.
    if not r.has_property('CA'):
        try:
            raw.decode('utf-8-sig');encoding='utf-8-sig'
        except UnicodeDecodeError:
            try:
                decoded=raw.decode('gb18030')
                encoding='gb18030' if re.search('[\u3400-\u9fff]',decoded) else None
            except UnicodeDecodeError:encoding=None
        if encoding:
            s=sgf.Sgf_game.from_bytes(raw,override_encoding=encoding);r=s.get_root()
            notes.append('棋谱未声明编码，已按 '+encoding+' 读取')
    n=s.get_size()
    def get(k,default=''):
        return r.get(k) if r.has_property(k) else default
    rule=str(get('RU','Chinese')).lower()
    rules='japanese' if 'japan' in rule else 'korean' if 'korea' in rule else 'chinese'
    if rules=='korean':rules='japanese'
    komi=float(get('KM',6.5 if rules=='japanese' else 7.5))
    # Fox may emit AP twice. Inspect every raw AP value rather than get('AP').
    fox=r.has_property('AP') and any(b'foxwq' in ap.lower() for ap in r.get_raw_list('AP'))
    if fox and komi in (375,650):
        fixed={375:7.5,650:6.5}[komi]
        notes.append(f'已将野狐特殊贴目 {komi:g} 转换为 {fixed:g} 目');komi=fixed
    g=dict(id=uuid.uuid4().hex,title=name,size=n,komi=komi,rules=rules,black=get('PB','黑方'),white=get('PW','白方'),result=get('RE',''),date=get('DT',''),moves=[],initialStones=[],comments={},analysis={},sgf=base64.b64encode(raw).decode(),parserVersion=2,importNotes=notes)
    g['initialPlayer']=str(get('PL','W' if int(get('HA',0))>1 else 'B')).upper()
    count=0
    for idx,node in enumerate(s.get_main_sequence()):
        ab,aw,ae=node.get_setup_stones()
        if idx and (ab or aw or ae):raise ValueError('暂不支持中途摆子棋谱，请导出普通对局棋谱')
        if not idx:g['initialStones']=[(c,coord(p,n)) for c,ps in [('B',ab),('W',aw)] for p in ps]
        c,p=node.get_move()
        if c:g['moves'].append([c.upper(),coord(p,n)]);count+=1
        if node.has_property('C'):g['comments'][str(count)]=node.get('C')
    return replay(g)

def normalize_saved(g):
    if g.get('sgf') and g.get('parserVersion',0)<2:
        parsed=parse_sgf(base64.b64decode(g['sgf']),g['title'])
        if g.get('komi')!=parsed['komi'] or g.get('rules')!=parsed['rules']:g['analysis']={}
        for k in ('komi','rules','black','white','result','date','comments','parserVersion','importNotes'):g[k]=parsed[k]
    return g

def migrate_library():
    for path in LIB.glob('*.json'):
        g=json.loads(path.read_text('utf-8'))
        if g.get('sgf') and g.get('parserVersion',0)<2:
            backup=ROOT/'backups'/'before-sgf-format-fix';backup.mkdir(parents=True,exist_ok=True)
            dest=backup/path.name
            if not dest.exists():dest.write_bytes(path.read_bytes())
            g=normalize_saved(g)
            path.write_text(json.dumps(g,ensure_ascii=False),encoding='utf-8')

def save_game(g):
    g=normalize_saved(g);replay(g)
    id=g.get('id','')
    if not isinstance(id,str) or not re.fullmatch('[a-f0-9]{32}',id):id=uuid.uuid4().hex;g['id']=id
    g={k:v for k,v in g.items() if k not in ('positions','captures')}
    with LIB_LOCK:
        dest=LIB/(id+'.json')
        if dest.exists():
            old=normalize_saved(json.loads(dest.read_text('utf-8')))
            if all(old.get(k)==g.get(k) for k in ('moves','initialStones','initialPlayer','size','komi','rules')):
                merged=dict(old.get('analysis',{}))
                for t,a in g.get('analysis',{}).items():
                    if a.get('rootInfo',{}).get('visits',0)>=merged.get(t,{}).get('rootInfo',{}).get('visits',0):merged[t]=a
                g['analysis']=merged
        tmp=LIB/(id+'.tmp');tmp.write_text(json.dumps(g,ensure_ascii=False),encoding='utf-8');tmp.replace(dest)
    return {'id':id}

class Engine:
    def __init__(self):
        self.proc=None;self.jobs={};self.lock=threading.RLock();self.logs=[];self.ready=False;self.start_error=''
    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:return
            self.ready=False
            self.start_error=''
            for path in (ENGINE_PATH,MODEL_PATH,CONFIG_PATH):
                if not path.is_file():
                    self.start_error='引擎或模型尚未配置，请运行 python setup_engine.py；缺少文件：'+path.name
                    raise FileNotFoundError(self.start_error)
            self.proc=subprocess.Popen([str(ENGINE_PATH),'analysis','-config',str(CONFIG_PATH),'-model',str(MODEL_PATH)],cwd=ROOT/'engine' if (ROOT/'engine').is_dir() else ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            p=self.proc
            threading.Thread(target=self.read,args=(p,),daemon=True).start()
            threading.Thread(target=self.errors,args=(p,),daemon=True).start()
            threading.Thread(target=self.monitor,args=(p,),daemon=True).start()
    def monitor(self,p):
        while p.poll() is None:
            with self.lock:
                expired=[(id,'已达到 60 秒分析时限' if j.get('started') is not None else '等待引擎超时，请重试') for id,j in self.jobs.items() if j.get('continuous') and not j['done'] and ((j.get('started') is not None and time.monotonic()-j['started']>=AUTO_LIMITS['maxSeconds']) or (j.get('started') is None and time.time()-j['created']>=120))]
            for id,reason in expired:self.stop_analysis(id,reason)
            time.sleep(0.25)
    def stop_analysis(self,id,reason):
        with self.lock:
            j=self.jobs.get(id)
            if not j or j['done']:return
            j.update(done=True,stopReason=reason)
        try:self.send({'id':uuid.uuid4().hex,'action':'terminate','terminateId':id})
        except (OSError,ValueError):pass
    def errors(self,p):
        for line in p.stderr:
            with self.lock:
                self.logs=(self.logs+[line.strip()])[-40:]
                if 'Started, ready' in line:self.ready=True
            with (ROOT/'engine.log').open('a',encoding='utf-8') as f:f.write(line)
    def read(self,p):
        for line in p.stdout:
            try:d=json.loads(line)
            except ValueError:continue
            stop=''
            with self.lock:
                j=self.jobs.get(d.get('id'))
                if not j:continue
                if d.get('error'):j['error']=d['error'];j['done']=True
                elif 'rootInfo' in d and not j.get('cancelled') and not j['done']:
                    j['results'][str(d['turnNumber'])]=d
                    if not d.get('isDuringSearch'):j['finished'].add(d['turnNumber'])
                    if j.get('continuous'):stop=convergence_reason(j,d)
                    j['done']=len(j['finished'])>=j['total']
                    if j['done'] and j.get('continuous'):j['stopReason']=stop or '当前局面搜索已完成'
            if stop:self.stop_analysis(d['id'],stop)
        with self.lock:
            self.ready=False
            for j in self.jobs.values():
                if not j['done']:j.update(done=True,error='引擎已退出，请查看 engine.log')
    def send(self,d):
        with self.lock:
            self.proc.stdin.write(json.dumps(d)+'\n');self.proc.stdin.flush()
    def analyze(self,g,turns,visits,continuous=False):
        replay(g);self.start();id=uuid.uuid4().hex
        if not turns or any(type(t)!=int or t<0 or t>len(g['moves']) for t in turns):raise ValueError('无效分析手数')
        if continuous and len(turns)!=1:raise ValueError('持续分析只能针对当前局面')
        j=dict(results={},finished=set(),total=len(turns),done=False,error='',cancelled=False,continuous=continuous,started=None,stopReason='')
        with self.lock:
            if sum(not x['done'] for x in self.jobs.values())>=3:raise ValueError('分析任务较多，请等待或停止当前任务')
            self.jobs={k:v for k,v in self.jobs.items() if not v['done'] or time.time()-v.get('created',0)<3600}
            j['created']=time.time();self.jobs[id]=j
        q={k:g[k] for k in ('moves','initialStones','initialPlayer','komi','rules') if k in g}
        q.update(id=id,boardXSize=g['size'],boardYSize=g['size'],analyzeTurns=turns,maxVisits=AUTO_LIMITS['maxVisits'] if continuous else max(16,min(int(visits),10000)),includeOwnership=True,analysisPVLen=16,reportDuringSearchEvery=0.5)
        self.send(q);return {'id':id}
    def close(self):
        if self.proc and self.proc.poll() is None:self.proc.terminate()

engine=Engine();atexit.register(engine.close)

class Handler(BaseHTTPRequestHandler):
    def parse_request(self):
        if not super().parse_request():return False
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}',f'localhost:{PORT}'):
            self.send_error(403,'Local host required');return False
        return True
    def log_message(self,*a):pass
    def json(self,d,code=200):
        raw=json.dumps(d,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        p=urlparse(self.path).path
        try:
            if p=='/api/status':return self.json(dict(app='yijing',running=bool(engine.proc and engine.proc.poll() is None),ready=engine.ready,logs=engine.logs[-8:],engine='KataGo · 本地分析',model=MODEL_PATH.name,startError=engine.start_error))
            if p.startswith('/api/job/'):
                with engine.lock:
                    j=engine.jobs[p.split('/')[-1]]
                    return self.json({k:v for k,v in j.items() if k not in ('finished','samples','lastVisits')}|{'completed':len(j['finished'])})
            if p=='/api/library':
                items=[]
                for f in sorted(LIB.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                    try:
                        g=json.loads(f.read_text('utf-8'));items.append({k:g.get(k) for k in ('id','title','black','white','date')}|{'moves':len(g['moves'])})
                    except (ValueError,KeyError):pass
                return self.json(items)
            if p.startswith('/api/library/'):
                id=p.split('/')[-1]
                if not re.fullmatch('[a-f0-9]{32}',id):raise ValueError('无效棋谱编号')
                return self.json(replay(normalize_saved(json.loads((LIB/(id+'.json')).read_text('utf-8')))))
            if p not in ('/','/app.js','/style.css','/terrain.js','/terrain.html','/terrain-companion.js','/vendor/three.module.js','/vendor/OrbitControls.js','/vendor/THREE-LICENSE.txt'):return self.send_error(404)
            f=ROOT/'web'/('index.html' if p=='/' else p[1:]);raw=f.read_bytes();self.send_response(200);self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','txt':'text/plain; charset=utf-8'}[f.suffix[1:]]);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        except (ValueError,KeyError,FileNotFoundError) as e:self.json({'error':str(e)},400)
    def do_POST(self):
        try:
            # Only same-origin JSON requests may mutate the local service.
            if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):raise ValueError('请求来源不允许')
            if 'application/json' not in self.headers.get('Content-Type',''):raise ValueError('需要 JSON 请求')
            length=int(self.headers.get('Content-Length',0))
            if not 0<length<24000000:raise ValueError('文件过大')
            d=json.loads(self.rfile.read(length));p=urlparse(self.path).path
            if p=='/api/import':result=parse_sgf(base64.b64decode(d['data']),d.get('name','导入棋谱'))
            elif p=='/api/replay':result=replay(d)
            elif p=='/api/analyze':result=engine.analyze(d['game'],d['turns'],d.get('visits',200),d.get('continuous',False))
            elif p=='/api/cancel':
                with engine.lock:
                    j=engine.jobs.get(d['id'])
                    if j:j.update(done=True,cancelled=True)
                engine.send({'id':uuid.uuid4().hex,'action':'terminate','terminateId':d['id']});result={'ok':True}
            elif p=='/api/save':
                result=save_game(d)
            elif p=='/api/shutdown':
                engine.close();threading.Thread(target=self.server.shutdown,daemon=True).start();result={'ok':True}
            else:raise ValueError('接口不存在')
            self.json(result)
        except Exception as e:self.json({'error':str(e)},400)

if __name__=='__main__':
    os.chdir(ROOT)
    migrate_library()
    ThreadingHTTPServer.allow_reuse_address=False
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    def startup():
        try:engine.start()
        except (OSError,ValueError) as e:engine.start_error=str(e);print(e,flush=True)
    threading.Thread(target=startup,daemon=True).start()
    print(f'弈镜 http://127.0.0.1:{PORT}',flush=True)
    server.serve_forever()
