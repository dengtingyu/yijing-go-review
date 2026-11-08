"""Install a pinned, checksum-verified Windows x64 OpenCL engine and model."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import time
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parent
ENGINE_SHA='1710db1903ab921aa6837a9599c8474f8a59f057650217c5d9bc125ee393a9ff'
MODEL_SHA='9d7a6afed8ff5b74894727e156f04f0cd36060a24824892008fbb6e0cba51f1d'
ENGINE_URL='https://github.com/lightvector/KataGo/releases/download/v1.18.1/katago-v1.18.1-opencl-windows-x64.zip'
ENGINE_API='https://api.github.com/repos/lightvector/KataGo/releases/assets/527063230?download=1'
MODEL_URL='https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def verified(path,expected):
    return Path(path).is_file() and digest(path)==expected

def acquire(dest,expected,urls,local=None):
    if verified(dest,expected):print(f'Already verified: {dest.name}');return
    temporary=dest.with_suffix(dest.suffix+'.part')
    if local:
        if not verified(local,expected):raise ValueError(f'Checksum mismatch: {local}')
        shutil.copyfile(local,temporary)
    else:
        error=None
        for url in urls:
            for attempt in range(2):
                try:
                    req=urllib.request.Request(url,headers={'User-Agent':'Yijing-Go-Review','Accept':'application/octet-stream'})
                    with urllib.request.urlopen(req,timeout=90) as response,temporary.open('wb') as f:
                        total=0
                        while chunk:=response.read(1024*1024):
                            f.write(chunk);total+=len(chunk)
                            print(f'\rDownloading {dest.name}: {total//(1024*1024)} MB',end='',flush=True)
                    print()
                    if not verified(temporary,expected):raise ValueError('Downloaded file failed SHA256 verification')
                    error=None;break
                except (OSError,ValueError) as e:error=e;time.sleep(1)
            if error is None:break
        if error is not None:raise RuntimeError(f'Download failed; retry or use --engine-zip / --model-file: {error}')
    temporary.replace(dest)

def install(engine_zip=None,model_file=None,verify_only=False):
    target=ROOT/'engine';target.mkdir(exist_ok=True)
    archive=target/'katago.zip';model=target/'model.bin.gz'
    if verify_only:
        if not verified(archive,ENGINE_SHA) or not verified(model,MODEL_SHA):raise ValueError('Engine archive or model missing / checksum mismatch')
        if not (target/'katago.exe').is_file() or not (target/'local.cfg').is_file():raise ValueError('Run setup_engine.py to complete extraction/configuration')
        print('Engine archive and model SHA256 verified.');return
    if os.name!='nt':raise SystemExit('Automatic setup currently supports Windows x64 only. See README for manual configuration.')
    acquire(archive,ENGINE_SHA,[ENGINE_URL,ENGINE_API],engine_zip)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if not (target/info.filename).resolve().is_relative_to(target.resolve()):raise ValueError('Unsafe archive path')
        z.extractall(target)
    acquire(model,MODEL_SHA,[MODEL_URL],model_file)
    cfg=target/'local.cfg'
    if not cfg.exists():shutil.copyfile(ROOT/'configs/analysis.cfg',cfg)
    print('Ready. Run: python launch.pyw')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-zip',type=Path,help='Previously downloaded official ZIP')
    parser.add_argument('--model-file',type=Path,help='Previously downloaded pinned model')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    install(args.engine_zip,args.model_file,args.verify_only)
