"""Add a reversible 3D engine entry to a closed LizzieYzy installation."""
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def install(config_path, engine_index=0, port=18769, make_default=False):
    if not 1 <= port <= 65535: raise ValueError('端口必须在 1 到 65535 之间')
    path = Path(config_path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    settings = data['leelaz']['engine-settings-list']
    if not 0 <= engine_index < len(settings): raise ValueError('引擎序号超出范围')
    source = settings[engine_index]
    if 'lizzie_terrain.py' in source['command']:
        raise ValueError('请选择原来的 KataGo 引擎，避免重复嵌套联动扩展')
    if 'gtp' not in source['command'].split():
        raise ValueError('请选择使用 gtp 模式的 KataGo 引擎')
    python = Path(sys.executable)
    if python.name.lower() == 'pythonw.exe': python = python.with_name('python.exe')
    script = Path(__file__).resolve().with_name('lizzie_terrain.py')
    command = subprocess.list2cmdline([str(python), str(script), '--port', str(port)]) + ' -- ' + source['command']
    entry = copy.deepcopy(source)
    entry.update(name='KataGo · 3D 形势', command=command, preload=False, isDefault=make_default)
    existing = next((i for i,e in enumerate(settings) if 'lizzie_terrain.py' in e.get('command','')), None)
    index = len(settings) if existing is None else existing
    backup = path.with_name(path.name + '.terrain-backup-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path, backup)
    if existing is None: settings.append(entry)
    else: settings[index] = entry
    if make_default:
        for i, e in enumerate(settings): e['isDefault'] = i == index
        data.setdefault('ui', {})['default-engine'] = index
    temporary = path.with_name(path.name + '.terrain-writing')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,path)
    return backup, index


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',help='Close LizzieYzy first; path to its config.txt')
    parser.add_argument('--engine-index',type=int,default=0)
    parser.add_argument('--port',type=int,default=18769)
    parser.add_argument('--default',action='store_true')
    args=parser.parse_args()
    try:
        backup,index=install(args.config,args.engine_index,args.port,args.default)
        print(f'已添加引擎 #{index}: KataGo · 3D 形势\n原配置备份：{backup}')
    except (OSError,ValueError,KeyError,IndexError) as exc:
        parser.exit(1,f'安装失败：{exc}\n')
