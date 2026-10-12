# Windows 本地安装与排错

## 1. 准备你的电脑

项目实际运行在你的电脑，不需要将 MySQL 暴露给公网，也不需要先解决 GitHub 推送。

在 PowerShell 检查：

```powershell
py -3.12 --version
node --version
npm --version
Get-Service *mysql*
```

推荐 Python 3.12、Node.js 24 LTS、MySQL 8.4（已有 MySQL 8.0 也受支持，但本次实库验证版本为 8.4）。安装 Python 时勾选 `Add python.exe to PATH`，安装完关闭并重新打开终端。

已有 MySQL 可继续使用；在 MySQL Workbench 中先确认能够用自己的用户名和密码登录。默认主机 `127.0.0.1`、端口 `3306`、用户名 `root`，若你的安装不同就填写实际信息。项目使用新的 `career_platform` 数据库，不使用已有业务库。

## 2. 下载、解压、运行

将压缩包的内容放入 `E:\my_master_DT_workpace`。最终目录结构应是：

```text
E:\my_master_DT_workpace\backend
E:\my_master_DT_workpace\frontend
E:\my_master_DT_workpace\scripts
E:\my_master_DT_workpace\README.md
```

原先的 `.git` 目录保留。如果解压询问覆盖原先只有一行的 README，可用本项目 README 替换；不要覆盖你以后添加的个人文件。

在 PowerShell 中：

```powershell
cd E:\my_master_DT_workpace
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1 -Demo
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

在 CMD 中也可以执行同样的 `powershell ...` 两行命令。`ExecutionPolicy Bypass` 仅作用于本次 PowerShell 进程，不永久修改系统策略。

首次安装依赖需要联网。安装脚本会隐藏读取数据库密码，并保存在**仅本地**的 `backend\.env`；文件已被 `.gitignore` 排除。密码不会预填在压缩包中。前端从来不会读取数据库密码。

## 3. 不用自动脚本的手工方法

在项目根目录 PowerShell：

```powershell
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install --require-hashes -r backend\requirements.lock
Copy-Item backend\.env.example backend\.env
notepad backend\.env
```

仅在 `.env` 不存在时复制模板；已有文件不要覆盖。在编辑器中填写自己的 MySQL 参数：

```dotenv
DB_DRIVER=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD="在这里填你本地的数据库密码"
DB_NAME=career_platform
```

密码有引号或反斜杠时优先用自动脚本处理转义。不要将此文件内容发到聊天或提交到 Git。

后端终端：

```powershell
cd E:\my_master_DT_workpace\backend
.\.venv\Scripts\python.exe -m app.cli init-db --demo
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

另开一个前端终端：

```powershell
cd E:\my_master_DT_workpace\frontend
npm ci --no-audit --no-fund
npm run dev
```

浏览器打开 Vite 在终端显示的本机地址。开发默认前端端口 `5173`，后端端口 `8000`。Vite 将 `/api` 请求代理到后端，无需填写跨域配置。两个终端都要保持运行。

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:5173/api/health
```

两项应返回 `status=ok`、`database=mysql`。后端 API 文档位于后端的 `/docs` 路径。

## 4. 常见错误

| 情况 | 处理 |
| --- | --- |
| 找不到 `py` / `python` | 安装 Python，重开终端；有多个版本时优先 `py -3.12` |
| 找不到 `npm` / Node 版本过低 | 安装 Node.js 24 LTS，重开终端 |
| `2003` / 无法连接 MySQL | 确认 MySQL 服务正在运行，检查端口和主机 |
| `1045` / Access denied | 用 Workbench 验证用户名密码，修改本地 `.env`，再执行初始化 |
| `1044` / 无建库权限 | 由本机数据库管理员创建 `career_platform` 并给开发用户授予该库的建表及 CRUD 权限；不要提升公网访问范围 |
| 健康检查 `503` | 执行 `python -m app.cli init-db`，确认 `.env` 和库权限 |
| `8000` 或 `5173` 被占用 | 关闭之前启动的开发终端；脚本不会关闭无关进程 |
| 图表没有数据 | 打开右上角演示模式，确认初始化时使用了 `-Demo` |
| 提示画像冲突 `409` | 点击重新加载后再编辑；另一页面已保存了新版本 |
| GitHub `Connection was reset` | 本地开发不受影响；待网络恢复后再推送，不用关闭 TLS 验证 |

首次启动出错时，把**错误文字或错误编号**发给我；请不要发送 `.env` 或密码。

## 5. 后续上传 GitHub

确保 `.env` 不会被提交：

```powershell
cd E:\my_master_DT_workpace
git status --short
git check-ignore backend/.env
git add .
git commit -m "Build local career development platform"
git push -u origin main
```

推送前查看待提交文件；`backend/.env`、依赖、运行数据库和日志不应出现。不要使用强制推送。网络正常时再处理 GitHub 登录。
