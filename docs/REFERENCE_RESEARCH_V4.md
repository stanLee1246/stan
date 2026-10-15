# V0.4 数据科学项目参考调研

调研日期：2026-10-15。目标是从真实可访问的项目资料中选取适合本项目的交互、分析与实验方法，继续使用 Vue 3、FastAPI 和本地 MySQL。本文区分“实际读取的材料”“未能访问的官网”与“本项目的设计建议”；不把参考项目的功能算作本项目已经实现的功能。

本轮实际落地功能及使用入口见 [V0.4增强指南](FEATURES_V4.md)，测试结果见 [验证记录](VALIDATION.md)。

## 一、实际读取的七组参考

本次通过 HTTPS 读取了下列官方或项目维护者 GitHub 页面，均返回 HTTP 200。正文事实来自该页面 README 或源码文档字符串；没有运行第三方演示，也没有对其当前在线产品做完整测试。

| 参考 | 实际读取的链接 | 页面中核验到的内容 | 适合本项目借鉴的做法 |
| --- | --- | --- | --- |
| Datawhale《动手学数据分析》 | [hands-on-data-analysis](https://github.com/datawhalechina/hands-on-data-analysis) | README 将学习链路分为数据载入与观察、清洗与重构、建模与评估；第三单元明确要求评价模型 | 将“数据进入系统以后发生了什么”与“算法结果怎样比较”连成一条可演示路线；清洗报告、仓库、挖掘和评价各有真实输出 |
| Streamlit | [streamlit/streamlit](https://github.com/streamlit/streamlit) | README 列举输入组件、DataFrame、图表、布局与多页面，并强调交互式数据应用 | 为分析页面提供明确输入、当前范围、结果解释和数据表；继续使用现有 Vue 页面，无须更换框架 |
| Plotly Dash 开源示例 | [dash-sample-apps](https://github.com/plotly/dash-sample-apps)、[油气分析示例](https://github.com/plotly/dash-sample-apps/tree/main/apps/dash-oil-and-gas)、[门诊分析示例](https://github.com/plotly/dash-sample-apps/tree/main/apps/dash-clinical-analytics) | 总仓库 README 称包含 100 多个 Python/R 开源应用；油气示例明确描述顶部筛选与跨图联动；门诊示例描述向高流量日期钻取 | 点击路径或城市图表后更新范围与相关明细；提供可清除的筛选条件，让用户从“发现差异”继续走到“查看机会与比较” |
| Apache Superset | [apache/superset](https://github.com/apache/superset) | README 包含可视化探索、无代码图表构建、SQL 编辑器，以及用于统一维度与指标的轻量语义层 | 在图表旁说明计数对象、分母、未知值、数据类型和来源；让仓库聚合与页面统计能够核对 |
| Metabase | [metabase/metabase](https://github.com/metabase/metabase) | README 明确提到交互仪表盘的 filters、custom click behavior，以及将原始数据转为 analytics-ready tables | 将筛选、图表点击、明细查看、下一步操作连起来；提供空结果解释，而不只展示一组孤立图表 |
| Evidently | [evidentlyai/evidently](https://github.com/evidentlyai/evidently) | README 列出缺失、重复、范围、新类别与相关性等数据质量检查；报告可导出 JSON/HTML，测试可设通过与失败条件 | 把“清洗完成”细化成可核对的质量项；展示拒绝原因、覆盖率和未知值，并导出结果供答辩复核 |
| scikit-learn | [TF-IDF 源码文档](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/feature_extraction/text.py)、[排序指标源码文档](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/metrics/_ranking.py) | `TfidfTransformer` 解释词频、逆文档频率与 L2 归一化；`ndcg_score` 明确需要真实相关性 `y_true` 与预测分数 `y_score` | 用同一机会池比较透明规则与 TF-IDF 余弦相似度；没有人工相关性标签时，只报告覆盖与排名变化，不填写虚假的准确率或 NDCG |

这些是可用于毕业设计学习与业务借鉴的资料，不是本项目已集成的第三方服务。当前调研不构成“七个项目都优于其他项目”的排名。

## 二、官网访问受限与检索范围

下列官网地址在本次云环境请求中都被出站代理以 `CONNECT 403` 拒绝；不能据此判定网站本身不可用，也不宣称已经审阅其当前在线界面：

- [Streamlit Gallery](https://streamlit.io/gallery)
- [Dash 文档](https://dash.plotly.com/)
- [Superset 首个仪表盘教程](https://superset.apache.org/docs/creating-charts-dashboards/creating-your-first-dashboard/)
- [Metabase 交互仪表盘文档](https://www.metabase.com/docs/latest/dashboards/interactive)
- [Evidently 指标文档](https://docs.evidentlyai.com/metrics/explainer)
- [My Next Move 兴趣探索](https://www.mynextmove.org/explore/ip)
- [O*NET 技能说明](https://www.onetonline.org/help/online/skills)
- [scikit-learn 文本特征提取文档](https://scikit-learn.org/stable/modules/feature_extraction.html)

GitHub 的中文“招聘 数据分析 毕业设计”和英文“career recommendation tfidf”仓库搜索均能够读取。搜索结果同时包含教学、个人原型和营销项目，星数、标题中的“推荐系统”或“毕业论文”不足以证明实现质量，因此没有直接复制未审核的毕业设计代码，也没有把搜索命中视为完成竞品评测。

本次只读取公开资料。页面下载记录、网页正文与算法源码页面提取内容保存在忽略目录 `.local/research-v4/`，仅作为本地调研证据，不纳入应用或 Git 提交，也未发送用户问卷。上述两个 scikit-learn 模块的 `.rst` 文档页面请求另遇 HTTP 503，故算法事实引用的是实际成功读取的官方源码文档字符串。

## 三、转换为本项目可验收的改进

### 1. 从看图走向探索

路径分布和城市分布应允许选择范围，并同步更新相关图表、统计卡和原始机会明细。必须可见地展示当前条件、清除入口、来源类型、公告数量和未知值；图表中的一条公告不能被误读为一个岗位或一个录用名额。受限图表只显示 Top N 时，应说明范围。

从分析结果跳到机会列表时，需要携带相同条件；学生才能沿着“这个方向机会较多 → 查看相关公告 → 收藏比较 → 形成行动”继续操作。公开与模拟范围切换后，应撤销旧请求造成的过时结果。

### 2. 从单一推荐走向算法对照

实验使用同一画像版本、同一数据类型、同一候选机会版本和同一资格检查。可对照当前多维规则与 TF-IDF 文本相似度；文本相似度只说明描述与画像中词语的接近程度，不能直接解释为录用概率或人生适合度。

scikit-learn 源码文档中的默认平滑公式为：

```text
idf(t) = log((1 + 文档数) / (1 + 包含词 t 的文档数)) + 1
tfidf(t, d) = tf(t, d) × idf(t)
```

L2 归一化后的向量点积可计算余弦相似度。若本项目自行实现轻量版本，必须明确分词、词频、语料与归一化设置，不能只凭方法名称声称与 scikit-learn 的默认英文分词完全相同。空画像、空词表或没有共同词时，应解释结果限制。

无真实标注时可展示候选数、可评分数、Top K 重合与名次变化；这些指标描述两个方法的差异。准确率、Precision@K、Recall@K、NDCG 等效果评价需要独立人工相关性标签，不能把某个推荐方法自身产生的标签作为标准答案。

### 3. 从差距清单走向可执行的学习准备

将“目标机会要求但画像尚未填写的技能”汇总成学习建议，同时解释来自哪些公告、覆盖几个候选对象、是否只是字段缺失。用户自行选择学习项与小任务；完成任务可以更新行动记录，实际能力仍由学生补充和核对。

兴趣伙伴继续用于探索和解释，不参与硬性资格淘汰。不同职业路径的机会数量与数据质量可能不同，应在路径内讨论取舍，保留证据不足的说明。

### 4. 从清洗完成走向质量可审计

延续现有接入批次、去重、拒绝行、来源哈希与 ODS/DWD/DWS/ADS，补充容易理解的质量摘要与可导出结果。明确区分来源未标注、解析失败、用户未填写；不把未知值补成“无要求”。

数据质量通过与算法效果良好是不同结论：通过清洗只能说明满足已声明的格式与治理规则，不能证明来源事实准确，也不能证明推荐有效。

## 四、复用与边界

本轮借鉴的是公开说明中的业务思路与算法定义，不迁入第三方网站、图片、品牌、职业数据库或完整源码。Datawhale README 标示 CC BY-NC-SA 4.0；其他项目许可各有要求。若后续直接复用代码、教程文本或资产，应先核对具体文件许可并保留相应声明。

本地 MySQL 仍是主运行数据库；不为展示参考网站而引入 Superset、Metabase 或 Evidently 等额外服务。实际新增页面、接口、测试和当前限制应以项目本轮功能说明及验证记录为准。
