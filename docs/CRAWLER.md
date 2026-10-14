# 衡阳公开招聘公告采集

**2026-10-14实测更新：** 当前云机器通过管理员接口采集固定栏目，页面返回HTTP412，任务`blocked`，真实新增0；未启用回退。处理记录可在“数据加工全景”查看，原始错误在工作台采集记录保留。下方10月13日代理403为历史环境结果，不代表今天仍停在相同网络阶段。

## 范围与使用

管理员在“数据接入 / 公告采集”中选择来源后执行采集。当前固定来源为衡阳市人社局事业单位公开招聘栏目：

<https://www.hengyang.gov.cn/hysrsj/ywgz/sydwgkzp/index.html>

接口不接受任意 URL。未验证的就业网站没有加入来源表，避免把第三方信息标为官方。

1. `GET /api/admin/crawler/sources` 返回可选来源数组。
2. `POST /api/admin/crawler/run` 接受 `{"source_id":"hengyang_hr_public","limit":5,"allow_demo_fallback":false}`。
3. `GET /api/admin/crawler/runs` 返回最近 30 次运行、统计、错误及文档来源。

三个接口均要求已登录的管理员。一次运行最多获取 10 个内容页，包含一个栏目页和最多九个详情页；`limit` 范围为 1–10，达到总页面预算时会截断详情数量。每个请求至少间隔一秒，连接超时 10 秒，请求超时 15 秒，页面上限 2 MiB，TLS 证书验证保持开启。

采集先读取同域 `robots.txt`；禁止路径、不明网络故障、403/429 或超出交互间隔的 crawl-delay / request-rate 都会停止相应请求，不绕过限制。404/410 表示没有 robots 文件。详情与重定向必须使用已注册 HTTPS 域名、默认 443 端口，不允许凭据、查询参数、外部主机和解析到私有网络的域名。如果本地 DNS 不可用而环境已配置 HTTPS 代理，则由现有代理解析固定官方主机；不修改代理，也不打印代理值。不执行 JavaScript，不自动下载岗位附件。

## 数据含义与清洗

采集链路为“栏目链接 → HTML 详情 → 原文 SHA-256 与抓取时间 → 标题、明确的发布时间及正文 → 版本化机会表”。HTML 原文保存在 `raw_crawl_document.raw_content`，MySQL 类型为 LONGTEXT，支持复查解析。运行状态和错误保存在 `crawl_run`，操作写入审计日志。

**栏目公告不等于独立岗位。** 真实记录的类型为公告；学校、学历、专业、技能、报名条件及岗位附件需要管理员核验。`requirements_verified=false`，原始记录标记 `requirements_review`。发布机构标为“公告发布方”，不冒充用人单位。发布时间只读取显式元数据或“发布时间 / 发布日期”等标签；未找到时为 `null`。不把抓取日期当发布日期，不把正文里的任意日期当截止日期。截止日期保持 `null`，不编造专业、学历或技能。

相同来源地址与抽取事实重复时不新增机会版本；正文或明示发布日期等事实变化时新增版本，原始快照仍保留。机会表的正文展示摘要最多保留 10,000 个 Unicode 字符，确保不超过 MySQL TEXT 容量；原始表保留完整 HTML，元数据记录 `description_truncated` 与 `original_description_length`。完整正文摘要哈希参与版本判断，展示截断部分之后的变化也会产生新版本。原文哈希基于解码后的 UTF-8 HTML，而不是宣称网络字节级签名。真实公告使用 `data_kind=public`，与模拟数据分开查询和展示。

## 真实采集受阻与模拟样本

2026-10-13 的云机器只读探测中，本地 DNS 不可用，由现有 HTTPS 代理解析固定官方来源；实际采集器请求 `https://www.hengyang.gov.cn/robots.txt` 时，HTTPS CONNECT 被环境代理返回 403，运行记录为 `blocked` / `proxy_blocked`。未得到官方页面内容。这是环境网络限制证据，不能据此认定官网自身禁止采集，也不能宣称已经抓到真实公告。部署环境需要能通过正常网络或既有代理访问 `www.hengyang.gov.cn:443`；放行后重新运行仍会遵守 robots 策略。

默认不会在失败时生成数据。只有管理员显式勾选“失败时使用模拟样本”，采集失败且没有可用真实公告时才进入 `demo_fallback`。原始失败仍保存在 `errors`，模拟来源使用 `https://example.com/synthetic-hengyang/...`，标题以 `（模拟）` 开头，元数据 `origin=synthetic`，发布 / 截止时间不编造。正常采到部分真实公告时，不混入模拟数据。

`data/crawler-fixtures/hengyang-demo.json` 提供八种衡阳就业、实习和事业单位合成机会，供离线毕业设计演示。`seed_crawl_demo(db, admin_id)` 可在本地初始化流程调用，无须网络，重复调用不会重复创建机会。两个 HTML 样本是人工编写的结构测试页面，不是抓取到的真实公告。

## 验证

`backend/tests/test_crawling.py` 使用 httpx MockTransport 验证栏目 / 详情抽取、显式日期、未知资格保留、robots 禁止、跨域重定向、页面大小、私有地址、原文与版本、重复导入、失败后的模拟标记和管理员权限。模板改变、robots 变化、来源封锁会显示明确错误；需要核对真实网页并调整解析规则，不能把测试样本当成真实数据验收。
