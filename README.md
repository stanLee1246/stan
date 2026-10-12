# 知途 · 学生职业发展辅助决策平台

面向湖南交通工程学院学生的毕业设计第一版。Vue 3 + Vite + ECharts 前端，FastAPI + SQLAlchemy + Alembic 后端，**正式本地开发使用 MySQL 8.0 / 8.4**。不依赖云数据库、付费 API、学校 SSO 或 Docker；Docker 仅用于可选的开发验证。

## 在你的 Windows 电脑运行

1. 安装 Python 3.12、Node.js 24 LTS（或 22.12+），启动已安装的 MySQL 服务。
2. 把项目压缩包解压到 `E:\my_master_DT_workpace`。该目录下应直接存在 `backend`、`frontend`、`scripts`；保留原有 `.git`，不要解压出额外一层目录。
3. 在此目录打开 PowerShell，执行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1 -Demo
   powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
   ```

安装脚本会询问本地 MySQL 主机、端口、用户名和密码，密码输入不回显。使用你自己的 MySQL 密码，不要改成下面的演示账户密码。默认创建独立数据库 `career_platform`；不删除已有数据库。已有 `backend/.env` 会保留。

启动脚本会打开本机浏览器；保持 PowerShell 窗口运行，按 Enter 停止本次启动的前后端。**这些步骤需要在你的电脑执行；当前云机器无法操作你的 E 盘。**

详见 [Windows 操作与排错](docs/WINDOWS.md)，包含不用脚本的手工启动方法。

## 演示账户与验收流程

只在使用 `-Demo` / `--demo` 时创建下列公开演示账户。它们用于本机功能测试，不用于公网部署。

| 角色 | 用户名 | 演示密码 |
| --- | --- | --- |
| 学生 | `demo_student` | `DemoStudent123!` |
| 管理员 | `demo_admin` | `DemoAdmin123!` |

1. 打开右上角“演示数据”：查看 180 条**模拟**去向记录与 7 条模拟机会。
2. 学生登录 → 个人画像：填写 Python、SQL，城市长沙、衡阳，勾选多个意向，保存 V1。
3. 发展机会 → 生成我的推荐：查看按路径分组的技能匹配、差距和资格待核对提示。
4. 修改技能保存 V2，再生成推荐：画像时间线保留 V1，推荐历史保留当时的机会内容。
5. 管理员登录 → 数据工作台：使用 `data/demo-outcomes.csv` 导入模拟数据，查看接受、拒绝、重复率和完整率；重复导入不会新增事实记录。
6. 学生提交公开经验 → 管理员审核 → 公开可见 → 学生撤回后不再公开。

默认关闭演示模式。真实记录尚未导入时显示“暂无已核实数据”，不将模拟数字当学校就业率。

## 当前实现范围

| 模块 | 已实现 |
| --- | --- |
| 账户与权限 | 普通注册、scrypt 密码散列、限时且可撤销的会话、学生/管理员权限 |
| 发展总览 | 专业/届次/来源筛选，去向、城市和样本届次图表，口径、观察日和批次标记 |
| 学校概况 | 公开资料入口、真实指标空状态；不编造办学规模 |
| 个人画像 | 多技能、多城市、多意向、未知值、SCD2 有效期、版本历史和并发冲突检测 |
| 发展机会 | 分路径筛选、来源、截止日期、版本录入、过期隐藏 |
| 推荐 | 可解释结构化规则、硬条件过滤、观测权重归一、技能差距、分路径候选、历史快照 |
| 校友经验 | 单独公开授权、管理员审核、本人撤回；普通注册不等于学校或校友身份核验 |
| 数据工作台 | UTF-8 CSV 校验、原始内容与 SHA-256、批次质量报告、冲突拒绝、操作审计 |

推荐分是参考排序分，不是就业/升学概率。复杂招考资格始终提示核对原文。报告汇总与逐人记录不可合并；不同逐人来源需分别选择。真实数据只允许导入获得授权且已匿名的记录。

这是可运行的第一阶段工程。**尚未实现或验证**：学校身份认证、真实公告自动采集、公开报告指标加载、完整共享维表与 DWS/ADS 预聚合、TF-IDF 对照、PySpark 性能实验、论坛评论/举报、用户数据删除申请和真实推荐效果实验。工作计划见 [设计说明](docs/ARCHITECTURE.md)；用户提供的方案保留在 [毕业设计原方案](docs/graduation-design-plan.md)，其中提到的旧 `career-starter.zip` 与测试结果不属于本工程。

## 目录

```text
backend/              Python 服务、锁定依赖、数据库迁移、后端测试
frontend/             Vue 页面、图表、API 客户端、浏览器验证
data/                 匿名逐人 CSV 模板与模拟 CSV
scripts/              Windows 本地脚本与云验证脚本
docs/                 本地指南、数据字典、设计说明、验证记录
```

## 手工开发与验证

后端工作目录是 `backend`，配置模板是 `.env.example`。使用 **Python 3.11–3.13，推荐 3.12**。前端工作目录是 `frontend`。

```powershell
# Windows / backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic current
# 创建真实管理员，交互输入密码，不使用公开演示账户
.\.venv\Scripts\python.exe -m app.cli create-admin

# frontend
npm run build
```

默认测试使用独立 SQLite 测试库，覆盖业务行为。在一次性 MySQL 上执行同一套测试：

```powershell
# 仅对一次性开发 MySQL 使用；会反复重建 career_platform_tests 中的表。
# 如果这个数据库中已有你需要的数据，不要运行此命令。
$env:TEST_MYSQL = '1'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:TEST_MYSQL
```

浏览器操作测试需要运行前后端，并准备演示数据。它会更新演示学生画像和测试来源，建议只针对独立验证数据库运行；重复运行会再增加两个画像版本，导入会跳过已有记录。

```powershell
# frontend：安装浏览器，再运行已有浏览器测试
npx playwright install chromium
npx playwright test
```

`.env`、数据库、日志、依赖目录和浏览器产物均被 Git 忽略。提交前使用 `git status --short` 检查，不要把个人 MySQL 密码、学生原始数据或 `.env` 上传。
