"""Double-click launcher; no terminal window, no duplicate engines."""
import json, os, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:'+os.environ.get('YIJING_PORT','18765')
def ready():
    try:
        d=json.load(urllib.request.urlopen(URL+'/api/status',timeout=2))
        return d.get('app')=='yijing'
    except Exception:return False
if not ready():
    python=Path(sys.executable).with_name('python.exe') if os.name=='nt' else Path(sys.executable)
    log=(ROOT/'server.log').open('a',encoding='utf-8')
    subprocess.Popen([str(python),str(ROOT/'server.py')],cwd=ROOT,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    for _ in range(30):
        if ready():break
        time.sleep(.25)
webbrowser.open(URL)
