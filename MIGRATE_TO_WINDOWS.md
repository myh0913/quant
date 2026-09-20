# 迁移到 Windows 电脑运行

> 本文档面向「把项目从 macOS/Linux 拷到 Windows」这一一次性操作。
> 不是日常开发文档，迁完即可归档。日常使用看 `start-all.sh` / `quant-web/README.md`。

---

## 0. 全文速查（30 秒读完照做）

| 步骤 | 在哪台机器 | 干什么 | 预计耗时 |
|---|---|---|---|
| 1 | 旧机器 | 用 rsync 打包（排除 `.venv`/`node_modules`/`dist`/`data/raw`/`logs`） | 2 分钟 |
| 2 | 传输 | `tar.gz` + `.env` 用 U 盘/网盘拷到 Windows | 取决于网速 |
| 3 | 新机器 | 装 Python 3.11+、Node 20 LTS | 10 分钟 |
| 4 | 新机器 | 解压到 `D:\quant\project\`（**无空格、无中文**） | 1 分钟 |
| 5 | 新机器 | 建 venv → `pip install -e ".[eltdx,dev]"` | 5–15 分钟 |
| 6 | 新机器 | 拷 `.env` 到 `quant-system\.env` | 1 分钟 |
| 7 | 新机器 | `npm install` + `npm run build` | 5–10 分钟 |
| 8 | 新机器 | 双击 `start-all.cmd` 启动 | 1 分钟 |

总耗时：30–60 分钟（首次需要装依赖）。

---

## 1. 文件传输：拷什么、不拷什么

项目里大部分内容可以**在新机器上重新生成**，拷过去反而慢、出问题：

### ✅ 必须拷（代码 + 配置）

```
project/
├── quant-system/
│   ├── src/                  # 全部代码
│   ├── tests/                # 测试
│   ├── pyproject.toml        # Python 依赖声明
│   ├── .env.example          # 环境变量模板（**不含密钥**）
│   ├── .gitignore
│   ├── README.md
│   ├── ONBOARDING.md
│   ├── PROJECT_RULES.md
│   ├── PROJECT_STATUS.md
│   └── docs/                 # 全部 6 个技术文档
├── quant-web/
│   ├── src/                  # 前端代码
│   ├── backend/              # Flask 后端
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   ├── run.sh            # 仅参考（Windows 不跑这个）
│   │   ├── .secret_key       # ⭐ 会话签名密钥（如已有）必须拷
│   │   └── users.json        # ⭐ 用户账号数据（如已有）必须拷
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   └── index.html
├── start-all.cmd             # ⭐ Windows 启动脚本（已含）
└── stop-all.cmd              # ⭐ Windows 停止脚本（已含）
```

### ✅ 建议拷（小，价值高）

```
quant-system/data/advice/    # 历史建议报告（KB~MB 级，保留历史查看）
```

### ❌ **不要拷**（拷了反而坏）

```
quant-system/.venv/                      # Python 虚拟环境（含 macOS/Linux 二进制）
quant-system/data/raw/                   # 原始响应缓存（可重建）
quant-system/__pycache__/
quant-system/.pytest_cache/
quant-system/src/**/__pycache__/
quant-web/node_modules/                  # ~500MB，含 macOS/Win 的二进制差异
quant-web/dist/                          # build 产物，重新生成即可
logs/                                    # 旧日志，无价值
.DS_Store                                # macOS 残留
*.tsbuildinfo                            # TS 增量编译缓存
```

### 旧机器打包命令

```bash
# rsync 排除清单（macOS/Linux）
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'node_modules' --exclude 'dist' \
  --exclude 'data/raw' --exclude 'logs' --exclude '.DS_Store' \
  --exclude '*.tsbuildinfo' \
  project/  /tmp/project-migrate/

# 打包
cd /tmp && tar czf project-migrate.tar.gz project-migrate/
# U 盘拷走，或 scp 到 Windows
```

### 密钥单独拷（**永远不与代码混传**）

```bash
# 旧机器
scp quant-system/.env 用户@windows:/tmp/quant-keys/
# 或者 U 盘单独拷
```

---

## 2. Windows 装基础环境

装这 3 个，全部装到无空格路径（默认 `C:\Program Files\` 也行，但建议 `C:\tools\`）：

| 软件 | 版本 | 下载 | 验证命令 |
|---|---|---|---|
| **Python** | **3.11 或 3.12**（必须 3.11+） | https://www.python.org/downloads/ | `python --version` |
| **Node.js** | **20 LTS** 或 **22 LTS** | https://nodejs.org/zh-cn | `node --version` `npm --version` |
| **Git** | 任意最新版 | https://git-scm.com/download/win | `git --version` |

### ⚠️ Python 安装选项

- ✅ 勾 **"Add Python to PATH"**（最重要）
- ✅ 选 **"Customize installation"**，**Disable path length limit**
- 路径避免空格：`C:\Python311\` 比 `C:\Program Files\Python311\` 安全

### 可选但强烈推荐

- **Visual Studio Build Tools** — 装 [eltdx 数据源](https://pypi.org/project/eltdx/) 需要 C++ 编译器
  - 下载：https://visualstudio.microsoft.com/visual-cpp-build-tools/
  - 勾「**使用 C++ 的桌面开发**」（约 6GB）

> 如果不装 VS Build Tools，跳过 eltdx，改用 hithink 数据源（见 §6 退路方案）。

---

## 3. 解压到无坑路径

**重要：路径必须无空格、无中文**，否则：

- `pip install` 莫名失败
- npm install 路径解析乱码
- venv 创建失败

```powershell
# 推荐：D:\quant\project\
Expand-Archive project-migrate.tar.gz -DestinationPath D:\quant\
# tar.gz 需要 7-Zip 或 tar 命令（Win10 1803+ 自带 tar）：
tar -xzf project-migrate.tar.gz -C D:\quant\
```

最终结构：

```
D:\quant\
└── project\
    ├── quant-system\
    ├── quant-web\
    ├── start-all.cmd
    └── stop-all.cmd
```

---

## 4. 装 Python 依赖

**用 PowerShell，不要用 CMD**（CMD 不识别 `Activate.ps1`，路径转义也坑）。

### 4.1 首次启用 PowerShell 脚本权限

首次在 PS 跑 `.ps1` 会报「无法加载文件，因为在此系统上禁止运行脚本」。解决：

```powershell
# 用管理员身份打开 PowerShell（右键开始菜单 → Windows PowerShell (管理员)）
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# 输入 Y 回车，关闭 PS
```

### 4.2 建虚拟环境 + 装依赖

```powershell
cd D:\quant\project\quant-system

# 建 venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 升级 pip（避免老 pip 解析新包失败）
python -m pip install --upgrade pip

# 装本项目 + eltdx 数据源
pip install -e ".[eltdx,dev]"
```

**国内网络加速**（可选）：

```powershell
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install -e ".[eltdx,dev]"
```

### 4.3 验证后端模块能加载

```powershell
# 测试
.\.venv\Scripts\python -m pytest tests\ -q

# 单跑一次盘后任务（验证数据源能联网）
.\.venv\Scripts\python -m quant_system.scheduler --once postmarket
```

不报错 = 后端 OK。

### 4.4 放密钥

```powershell
# 把 U 盘里的 .env 拷进来
Copy-Item E:\quant-keys\.env D:\quant\project\quant-system\.env

# 验证能读
Get-Content D:\quant\project\quant-system\.env
# 应该看到 HITHINK_FINANCE_API_KEY=... / XUANGUTONG_IVANKA_TOKEN=... / TELEGRAM_CHAT_ID=...
```

---

## 5. 装前端依赖 + 构建

```powershell
cd D:\quant\project\quant-web

# 用国内镜像（重要！npm 默认源在 Win 上经常卡）
npm config set registry https://registry.npmmirror.com

npm install

# 构建产物到 dist/，由后端托管（同源部署，无 CORS）
npm run build
```

构建完 `dist/` 目录会生成 ~2MB 静态文件。

> 💡 不 build 也能用，但需要开两个端口（前端 5273 + 后端 8000）；build 后只开 8000 一个端口（同源模式），更简单。生产环境推荐 build。

---

## 6. 启动（两种模式）

### 模式 A：单端口同源（⭐ 推荐，端口简单）

后端 8000 同时托管前端 `dist/`，只访问 `http://localhost:8000`。

```powershell
# 1) 后端（一个终端，常驻）
cd D:\quant\project\quant-web\backend

# 读 token（PowerShell 写法）
Get-Content ..\..\quant-system\.env | ForEach-Object {
  if ($_ -match '^XUANGUTONG_IVANKA_TOKEN=(.*)') {
    $env:XUANGUTONG_IVANKA_TOKEN = ***
  }
}

# 设路径（注意用反斜杠）
$env:QUANT_ADVICE_DIR = "D:\quant\project\quant-system\data\advice"
$env:QUANT_WEB_DIST   = "D:\quant\project\quant-web\dist"

# 启动
python main.py
```

打开 `http://localhost:8000` 即可。

调度器另起终端：
```powershell
cd D:\quant\project\quant-system
.\.venv\Scripts\python -m quant_system.scheduler
```

### 模式 B：双端口（开发调试用，对应 macOS 原 `start-all.sh`）

直接双击项目根目录的 **`start-all.cmd`**：

```cmd
:: D:\quant\project\start-all.cmd
@echo off
chcp 65001 >nul
echo === 启动量化全套（Windows 版）===
cd /d "%~dp0"

:: 读 token
for /f "tokens=1,* delims==" %%a in ('findstr /b "XUANGUTONG_IVANKA_TOKEN=" quant-system\.env') do (
  set "TOKEN=%%b"
)

:: ---- 1. 后端 ----
netstat -ano | findstr ":8000.*LISTENING" >nul
if %errorlevel%==0 (
  echo ⏭ 后端已在运行（:8000）
) else (
  echo 🚀 启动后端 :8000
  cd quant-web\backend
  set "QUANT_ADVICE_DIR=%~dp0quant-system\data\advice"
  set "QUANT_WEB_DIST=%~dp0quant-web\dist"
  start "QuantBackend" /min python main.py
  cd /d "%~dp0"
)

:: ---- 2. 前端 ----
netstat -ano | findstr ":5273.*LISTENING" >nul
if %errorlevel%==0 (
  echo ⏭ 前端已在运行（:5273）
) else (
  echo 🚀 启动前端 :5273
  cd quant-web
  start "QuantFrontend" /min npm run dev -- --host 0.0.0.0 --port 5273
  cd /d "%~dp0"
)

:: ---- 3. 调度器 ----
tasklist /fi "windowtitle eq QuantScheduler" | findstr "QuantScheduler" >nul
if %errorlevel%==0 (
  echo ⏭ 调度器已在运行
) else (
  echo 🚀 启动调度器
  cd quant-system
  start "QuantScheduler" /min .venv\Scripts\python.exe -m quant_system.scheduler
  cd /d "%~dp0"
)

timeout /t 3 /nobreak >nul
echo.
echo ✅ 前端     http://localhost:5273
echo    后端健康 http://localhost:8000/health
echo    今日建议 http://localhost:8000/api/advice
echo    日志     %~dp0logs\
pause
```

停止：

```cmd
:: stop-all.cmd
@echo off
chcp 65001 >nul
echo 停止调度器...
taskkill /fi "windowtitle eq QuantScheduler" /f >nul 2>&1
echo 停止前端...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5273.*LISTENING"') do taskkill /pid %%a /f >nul 2>&1
echo 停止后端...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do taskkill /pid %%a /f >nul 2>&1
timeout /t 1 /nobreak >nul
echo ✅ 全部已停
pause
```

---

## 7. Windows 专属坑清单

按出现频率排，**前 3 个必踩**：

| # | 坑 | 症状 | 解法 |
|---|---|---|---|
| 1 | **路径含空格或中文** | pip/npm 莫名失败 | 必须 `D:\quant\project\`，**不要** `D:\Program Files\quant\我的项目\` |
| 2 | **eltdx 编译失败** | `pip install eltdx` 报 `Microsoft Visual C++ 14.0 required` | 装 [VS Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) 并勾选「使用 C++ 的桌面开发」 |
| 3 | **PowerShell 禁止脚本** | 跑 `.ps1` 报红字 | §4.1 步骤，管理员 PS 跑 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| 4 | 防火墙弹窗 | 启动后浏览器连不上 8000/5273 | Windows 防火墙弹窗选「允许访问」（专用网络勾选） |
| 5 | `start-all.sh` 里的 `lsof` / `nohup` | 直接跑 bash 脚本会报错 | **用本仓库的 `start-all.cmd`**，不要硬撑 bash（想用 bash 需装 Git Bash 或 WSL） |
| 6 | `.venv\Scripts\` 不是 `.venv/bin/` | bash 路径习惯会找不到 python | 用 `.\.venv\Scripts\python.exe` 或 `.\.venv\Scripts\Activate.ps1` |
| 7 | `tsconfig.tsbuildinfo` 冲突 | `npm run build` 报错 | 删 `quant-web\tsconfig.tsbuildinfo` 后重 build |
| 8 | CRLF 换行 | U 盘拷过去的 `.sh` 在 Git Bash 跑不了 | Windows 上**直接用 `.cmd`**，不要 `.sh` |
| 9 | 时区 | 调度器按 Asia/Shanghai 调度，Win 默认时区 | Win10/11 设置 → 时间 → 时区改为「(UTC+08:00) 北京」 |

---

## 8. eltdx 装不上的退路方案

如果不装 VS Build Tools，`pip install eltdx` 会失败。两个选择：

### 选择 A：装 VS Build Tools（推荐，5–10 分钟）

下载 → 勾「使用 C++ 的桌面开发」→ 装完重启 PowerShell 重试 `pip install -e ".[eltdx,dev]"`。

### 选择 B：跳过 eltdx，只用 hithink + 选股通（不推荐，但能跑）

```powershell
# 不带 eltdx extra
pip install -e ".[dev]"
```

代码层面需要修改 `quant-system/src/quant_system/datasource/` 跳过 eltdx 数据源（hithink 的竞价数据精度不如 eltdx）。

> 除非有特殊原因，**强烈建议走 A**，eltdx 的竞价数据是策略核心。

---

## 9. 日常使用流程（迁完之后）

每天：

```cmd
:: 早上 8:50 双击启动
D:\quant\project\start-all.cmd

:: 晚上收市后双击停止
D:\quant\project\stop-all.cmd
```

查看日志：

```powershell
# 实时看调度器日志
Get-Content D:\quant\project\logs\scheduler.log -Wait

# 看后端日志
Get-Content D:\quant\project\logs\backend.log -Tail 50
```

### 开机自启（可选）

把 `start-all.cmd` 的快捷方式扔到启动文件夹：

```powershell
# Win+R 输入 shell:startup 回车，会打开启动文件夹
# 把 start-all.cmd 的快捷方式拖进去
```

---

## 10. 验证清单（迁移完一项一项打勾）

- [ ] Python `python --version` 输出 3.11+
- [ ] Node `node --version` 输出 v18+
- [ ] `D:\quant\project\quant-system\.venv\` 存在
- [ ] `pytest` 全绿（`.\.venv\Scripts\python -m pytest tests\ -q`）
- [ ] `quant-system\.env` 含 `HITHINK_FINANCE_API_KEY` / `XUANGUTONG_IVANKA_TOKEN` / `TELEGRAM_CHAT_ID`
- [ ] `quant-web\node_modules\` 存在
- [ ] `quant-web\dist\` 存在（build 后）
- [ ] `start-all.cmd` 双击后控制台输出 `✅ 前端 http://localhost:5273` / `✅ 后端健康 http://localhost:8000/health`
- [ ] 浏览器打开 `http://localhost:8000/health` 返回 `{"ok":true}`
- [ ] 浏览器打开 `http://localhost:8000/api/advice` 返回建议列表（空数组 `[]` 也算正常）
- [ ] `http://localhost:8000/api/sentiment` 返回情绪数据
- [ ] 调度器日志 `logs\scheduler.log` 在 09:25 / 09:26 / 17:00 有产出（首次跑可能空，等下一个交易日）
- [ ] `stop-all.cmd` 双击后 8000/5273 端口都释放（`netstat -ano | findstr ":8000"` 看不到 LISTENING）

---

## 11. 常见问题

### Q1：双击 `start-all.cmd` 闪退

**原因**：脚本里 `pause` 在末尾，但窗口被 `start /min` 隐藏了，看不到错误。
**排查**：

```cmd
:: 改用手动逐个启动，定位哪个出错
cd D:\quant\project\quant-web\backend
python main.py
```

### Q2：调度器启动后没数据

**原因 A**：`QUANT_ADVICE_DIR` 路径配错。
**排查**：检查 `quant-system\logs\scheduler.log` 第一行有没有报路径错误。

**原因 B**：当前是非交易时段（周末/节假日/午休），调度器会跳过。
**排查**：`python -m quant_system.scheduler --once postmarket` 手动跑一次。

### Q3：前端 build 报错 "Cannot find module"

**原因**：`node_modules` 没装好或被旧缓存污染。
**解决**：

```powershell
cd D:\quant\project\quant-web
Remove-Item -Recurse -Force node_modules
Remove-Item package-lock.json -ErrorAction SilentlyContinue
npm cache clean --force
npm install
npm run build
```

### Q4：后端报错 "Address already in use"

**原因**：8000 端口被占用（旧实例没杀干净）。
**解决**：

```powershell
# 找到占用进程
netstat -ano | findstr ":8000"
# 杀掉（替换 <PID> 为实际进程号）
taskkill /PID <PID> /F
```

### Q5：选股通 / 同花顺 API 报 401/403

**原因**：`.env` 里的 token 过期或复制错误。
**排查**：

```powershell
Get-Content D:\quant\project\quant-system\.env
# 检查 token 字符串长度、无空格、无换行
```

---

## 12. 卸载

```powershell
# 1. 停服务
D:\quant\project\stop-all.cmd

# 2. 删除项目（trash 不彻底，直接删也行，反正是迁移用的临时副本）
Remove-Item -Recurse -Force D:\quant\project

# 3. 可选：卸载 Python / Node / VS Build Tools（控制面板 → 程序和功能）
```

---

## 附录：路径速查表

| 作用 | Windows 路径 |
|---|---|
| 项目根 | `D:\quant\project\` |
| Python 虚拟环境 | `D:\quant\project\quant-system\.venv\` |
| Python 解释器 | `D:\quant\project\quant-system\.venv\Scripts\python.exe` |
| 密钥文件 | `D:\quant\project\quant-system\.env` |
| 建议落盘目录 | `D:\quant\project\quant-system\data\advice\` |
| 前端构建产物 | `D:\quant\project\quant-web\dist\` |
| 后端入口 | `D:\quant\project\quant-web\backend\main.py` |
| 日志目录 | `D:\quant\project\logs\` |
| 启动脚本 | `D:\quant\project\start-all.cmd` |
| 停止脚本 | `D:\quant\project\stop-all.cmd` |
| 用户数据 | `D:\quant\project\quant-web\backend\users.json` |
| 会话密钥 | `D:\quant\project\quant-web\backend\.secret_key` |
