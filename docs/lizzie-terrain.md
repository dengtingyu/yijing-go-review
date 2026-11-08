# Lizzie / LizzieYzy 的 3D 形势联动扩展

这是 **GTP 外接式扩展**：放在 GUI 与原来的 KataGo 之间，在浏览器窗口显示当前局面的三维归属地形。不是往 Lizzie 安装目录里复制一个 JAR 的原生插件，也不修改 Lizzie 源码。它与 GUI 共用一个 KataGo 进程，不启动第二套分析。支持 `kata-analyze` 的其他 GTP 客户端也可手动接入。

## 已有 LizzieYzy：自动配置

准备 Python 3.11+ 和一套已经能工作的 KataGo GTP 引擎。先关闭 LizzieYzy，防止退出时覆盖配置。

在弈镜项目目录执行：

```powershell
python install_lizzie_terrain.py "C:\LizzieYzy\config.txt" --engine-index 0 --default
```

`--engine-index` 是原来的 KataGo 在 `engine-settings-list` 中的位置，从 0 开始。安装器复制它的模型、配置等参数，增加 **KataGo · 3D 形势** 引擎条目，并在配置旁保留一份带时间戳的备份。`--default` 把新条目设为默认；省略时需要在引擎菜单手动选择它。不要移动项目目录或 Python 安装位置，否则需要重新运行安装器更新路径。

重新打开 LizzieYzy，启用这个引擎，浏览器会自动打开 **http://127.0.0.1:18769/**。照常导入 SGF、翻手、试下、开始或停止分析即可；3D 窗口自动跟随真正发送给引擎的局面。鼠标悬停产生的 GUI 临时预览不会被当作新局面。

不想用时切回原引擎即可。要完全恢复，可关闭 GUI 后用旁边的 `config.txt.terrain-backup-...` 备份替换配置。原来的 KataGo 文件和配置都没有被改写。

## 原版 Lizzie / 其他 GTP 客户端：手动配置

将现有引擎命令：

```text
"C:\KataGo\katago.exe" gtp -model "C:\KataGo\model.bin.gz" -config "C:\KataGo\gtp.cfg"
```

改为下面的形式，使用本机真实路径：

```text
"C:\Python313\python.exe" "C:\yijing-go-review\lizzie_terrain.py" -- "C:\KataGo\katago.exe" gtp -model "C:\KataGo\model.bin.gz" -config "C:\KataGo\gtp.cfg"
```

`--` 后面完整保留原有命令。GUI 负责搜索的启停与上限，扩展不会主动发起额外搜索。需要端口区分多个实例时，在 `--` 前加 `--port 18771`；加 `--no-browser` 可关闭自动打开网页。不要同时让多个扩展占用同一端口。

## 数据含义与兼容范围

- 只从 KataGo 的 GTP 输出读取真实 `ownership`，黑色为偏黑，白色为偏白，高度表示归属倾向强度。曲面经过空间平均和边缘收坡，不能拿边缘高度当原始数值，也不等于传统的外势。
- 支持 9 / 13 / 19 路正方形棋盘、落子、提子、停一手、退棋、摆子、让子，以及引擎生成的落子。跟随 GUI 导入 SGF 后发送的 `clear_board` / `play` 序列。
- 命令被 KataGo 确认成功后才更新棋盘。换手时先清除旧地形，忽略延迟到达的上一局面结果；不会把旧归属贴到新局面上。
- 引擎直接执行 `loadsgf`、其他尺寸、非正方形棋盘暂不支持联动；显示明确提示。通过 GUI 导入棋谱即可使用常规重放路径。
- 默认自动读取 `-config` 和 `-override-config` 里的 `reportAnalysisWinratesAs`，并转换成统一的黑方视角。用特殊启动器或配置来源时，可显式加 `--perspective BLACK`、`WHITE` 或 `SIDETOMOVE`。
- 联动服务仅监听 `127.0.0.1`，只提供读取局面和页面的接口；不提供远程落子或执行命令接口。页面及 Three.js 均随仓库提供，运行时无需访问 CDN，也不上传棋谱。

已验证：本机 Windows、KataGo 1.18.1、LizzieYzy 2.5.3。原版 Lizzie 使用相同 GTP 接口，但尚未逐版本运行验证。退出 GUI / 引擎后联动服务同时退出。
