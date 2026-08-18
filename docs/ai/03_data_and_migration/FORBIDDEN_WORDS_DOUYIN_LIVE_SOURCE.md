# 抖音汽车直播违禁词库 —— 迁移依据文档（来源：甲方两份 PDF）

> 状态：**词条已确认，可作数据库迁移依据**
> 日期：2026-08-18（G1-DELTA 冻结方案后更新：违禁词只检测/审计，不再替换）
> 适用系统：auto_wechat · M01-抖音AI小高客服（抖音自动接待客服 · 违禁词检测功能）

---

## 1. 背景

甲方提供两份 PDF，要求提取抖音汽车直播场景的违禁词并写入数据库，作为 M01 客服违禁词检测功能的词库来源：

| 来源 | 文件 | 页数 |
|---|---|---|
| PDF-A | `直播违规注意事项.pdf` | 3 |
| PDF-B | `抖音汽车直播违禁词规避及辟谣指南.pdf` | 11 |

原文存放：`E:\work\project\project_info\Project_autowechat\`
提取文本（PyMuPDF，规避模型直接读 PDF 的 400 错误）暂存：`E:\tmp\wg01_m.txt` / `E:\tmp\wg02_m.txt`

## 2. 提取决策记录（2026-08-18 甲方确认）

| 决策项 | 结论 |
|---|---|
| A. 第一部分明确违禁词清单 | **全部纳入** |
| B. 疑似 OCR 乱码 / 错字词汇 | **直接忽略，不纳入** |
| C. 行为 / 场景描述类（非具体词汇） | **直接跳过，不转化为词条** |
| 覆盖范围 | **只保留与汽车、直播强相关的类别**，剔除房地产/教育/户口/无预售许可证等弱相关词条 |

### 2.1 被剔除的内容（明确不纳入）

- **乱码词汇**：市米好运增虫弟怒、最聚找、最峰、透留、独据、首迹、顾地、层晓、这这无几、绝不在有、不可女制、股堂、升值洪力无线、买到即嫌到、亚禁使用、违宗词、精丁德式装修、干X宏的歌、算一第二、金融汇币图片 等（共 25 项，详见提取过程记录，此处从略）。
- **行为/场景描述**：踩一捧一、衣着暴露/聚焦敏感部位、危险行为、挂机录播、展示微信截图、提及其他汽车品牌、福袋抽实物奖品、引导私下交易、招聘/招生/招商、抽烟喝酒赌博打麻将、恶意爱国营销、方言/连读误判 等——**不转词条**。
- **房地产/教育/户口等弱相关词条**：得房率、绿化率、容积率、CBD 坐标、地铁上盖、咫尺地铁站、万亩公园、学区房、承诺户口、蓝印户口、九年制教育、无预售许可证、楼王、墅王、黄金旺铺、黄金地段、寸土寸金 等。

## 3. 目标数据库结构对接

落库表结构（现有，`migrations/versions/0027_xiaogao_phase1_core.sql` / `app/models.py`）：

- `forbidden_word_libraries`：`library_key`(唯一)、`name`、`description`、`scope='global'`、`enabled=1`
- `forbidden_words`：`library_id`、`word`、`safe_word`、`severity`、`enabled=1`；`(library_id, word)` 唯一

### 3.0 现有实现机制（G1-DELTA 冻结方案，2026-08-18 已核实并更新）

项目内违禁词统一为**只检测/审计**机制，不再有"替换为 safe_word 继续发送"的替换路径：

**机制一：LLM 生成路径（抖音 AI 客服 `xg_douyin_ai_cs`）——"禁止 + 命中重生成 1 次 + 仍命中转人工"**
- 违禁词注入 system prompt，明确"回复中不得出现以下违禁词或其变体；如果无法避免，必须设置 manual_required=true"
- `reply_decision_service.py` 首调后确定性检查 `_check_forbidden_words`：**命中并入 `retry_combined`**（最多 1 次合并纠正，命中词注入第二次模型请求，总模型调用 ≤2）；retry 后与安全后处理后仍命中 → `manual_required=true`/`auto_send=false` 阻断转人工
- 词源：`request.forbidden_words` ← `load_forbidden_words_for_llm(db)`，在 `app/routers/douyin_ai_cs_proxy.py` 与 `app/routers/agents.py` 注入

**机制二（已废止）：代码层替换路径已删除**
- `forbidden_word_service.replace_forbidden_words` 已删除，替换为 `check_forbidden_words`（只检测/审计，不替换正文）
- 抖音人工私信保留原文发送；微信派单/自动通知/销售反馈/回访后通知销售**完全豁免**抖音违禁词（不替换、不阻断）
- 抖音自动回访话术发送前只检测（`check_forbidden_words`），命中阻断不发送
- 回访模板新增/编辑命中 → 400 `FORBIDDEN_WORD_HIT`+hits 拒绝保存

**`safe_word` 为兼容可选字段（不再作为活跃词过滤条件）**
- `forbidden_word_service._load_active_words` 不再过滤 `safe_word` 非空；空 `safe_word` 词条**仍进入 LLM 检查与检测**（不再静默失效）
- 前端 `SuperForbiddenWords.tsx` 已移除安全替换词录入/展示/必填校验
- 固定敏感词替换 `_replace_sensitive_words`（微信→绿泡泡、手机号→联系方式、个人号→v）已删除

### 3.1 词库规划（library_key）

现有 3 库直接复用，新增 7 库：

| library_key | 名称 | 复用/新增 | 来源类别 |
|---|---|---|---|
| `used_car_sales_base` | 二手车销售基础违禁词 | 复用 | 汽车行业特有（违规售卖） |
| `finance_compliance` | 金融方案合规词库 | 复用 | 金融相关 |
| `vehicle_condition_risk` | 车况承诺风险词 | 复用 | 车况承诺风险 |
| `extreme_ad_words` | 极限用语/绝对化用语 | 新增 | 最/一/级/极/极限无法考证 |
| `state_sensitive_words` | 涉政/权威/国家敏感词 | 新增 | 权威国家、涉政敏感 |
| `inducement_fraud_words` | 诱导/欺诈/限时消费词 | 新增 | 诱导欺诈、刺激消费、时限用语 |
| `contact_guidance_words` | 线下引流/联系方式引导词 | 新增 | 线下引流、私域引导 |
| `superstition_words` | 迷信用语 | 新增 | 迷信、风水（直播相关部分） |
| `incivility_words` | 不文明/歧视用语 | 新增 | 不文明用语 |
| `ip_event_words` | 版权/赛事/IP 词 | 新增 | 赛事营销、未授权 IP |

> 说明：以上 library_key 为建议值，迁移实现时可按需调整；词条归属以第 4 节表格为准。

## 4. 违禁词条清单（已确认）

> `safe_word` 为**兼容可选字段**（G1-DELTA 后不参与替换、不再必填，可留空；留空词条仍进入检测与 LLM 检查）。
> `severity` 取值建议：`critical`（涉政/联系方式/金融）/ `high` / `medium`。

### 4.1 汽车行业特有 —— 违规售卖二手车（→ `used_car_sales_base`）

来源：PDF-A「1.违规售卖二手车」、PDF-B「违规售卖/不接受投放」

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 故事车 | 二手车 | high | PDF-A 1 |
| 事故车 | 二手车 | high | PDF-A 1 |
| 瑕疵 | XX | medium | PDF-A 1 |
| 改装 | XX | high | PDF-A 1 / PDF-B 不接受投放 |
| 报废 | 二手车 | high | PDF-A 1 |
| 抵押车 | 二手车 | high | PDF-A 1 |
| 换件 | XX | high | PDF-A 1 |
| 过不了户 | XX | critical | PDF-A 1 |
| 收车 | 回收 | high | PDF-A 1 |
| 二手车回收 | 车辆回收 | high | PDF-B 不接受投放 |
| 加装 | XX | medium | PDF-A 1 |
| 升级 | XX | medium | PDF-A 1 |
| 改款 | XX | medium | PDF-A 1 |
| 车衣 | XX | medium | PDF-A 1 |
| 贴膜 | XX | medium | PDF-A 1 / PDF-B 不接受投放 |
| 车膜 | XX | medium | PDF-B 不接受投放 |
| 车贴 | XX | medium | PDF-B 不接受投放 |
| 轮毂 | XX | medium | PDF-B 不接受投放（改装语境） |
| 购置税 | 新政策 | high | PDF-B 不接受投放二 |
| 购置税全免 | 新政策 | high | PDF-B 不接受投放二 |
| 卖车 | 有车源 | high | PDF-B 违规售卖（未挂小风车时） |

> 注：PDF-B 明确"只提及'改'字也会触发违规"，单字"改"作为高危词建议单独评估是否入库（涉及"改款/改装/改车"等组合），迁移时由产品确认。

### 4.2 金融相关（→ `finance_compliance`）

来源：PDF-A「5.金融相关（小雪花）」、PDF-B 通用敏感词「21.价值」「27.其他」

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 分期 | 分期方案 | high | PDF-A 5 |
| 贷款 | 金融方案 | high | PDF-A 5 / PDF-B 27 |
| 置换 | 换购 | high | PDF-A 5 |
| 抵押 | XX | high | PDF-A 5 |
| 征信 | XX | high | PDF-A 5 |
| 按揭 | 月供方案 | high | PDF-A 5 |
| 黑户 | XX | critical | PDF-A 5/6 / PDF-B 3.1 |
| 金融 | XX | high | PDF-A 5 |
| 首付 | 购车方案 | high | PDF-A 5 / PDF-B 通用13 |
| 利息 | 费用 | high | PDF-A 5 |
| 利率 | 费率 | high | PDF-A 5 |
| 免息 | 分期方案 | high | PDF-A 5 / PDF-B 3.5 |
| 0首付 | 分期方案 | critical | PDF-B 通用13 |
| 免首付 | 分期方案 | critical | PDF-B 通用13 |
| 投资回报 | XX | medium | PDF-B 通用21 |
| 众筹 | XX | high | PDF-B 通用21 |
| 千亿价值 | XX | high | PDF-B 通用21 |
| 价值洼地 | XX | medium | PDF-B 通用21 |
| 价值天成 | XX | medium | PDF-B 通用21 |
| 抄涨 | XX | high | PDF-B 通用21 |
| 炒股不如买房 | XX | high | PDF-B 通用21（话术向，可评估） |

### 4.3 车况承诺风险（→ `vehicle_condition_risk`）

来源：PDF-A「1.违规售卖二手车」、PDF-B「类型八 虚假内容」

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 纯天然 | XX | medium | PDF-B 类型八 |
| 祖传 | XX | medium | PDF-B 类型八 |
| 特效 | XX | medium | PDF-B 类型八 |
| 无敌 | XX | medium | PDF-B 类型八 |
| 质量免检 | XX | high | PDF-B 类型一 |
| 无需国家质量检测 | XX | high | PDF-B 类型一 |
| 免抽检 | XX | high | PDF-B 类型一 |
| 样板间实景图 | 实景图 | low | PDF-B 通用27 |
| 效果图 | 示意 | low | PDF-B 通用27 |

### 4.4 极限用语 / 绝对化用语（→ `extreme_ad_words`）

> 覆盖来源：PDF-A「严禁使用极限用语」、PDF-B 类型二/三/四/五/六、通用敏感词 1/2/3/4/5/6/9/10/11、其他敏感词 2/3/4。
> 替换策略：绝对化用语建议整体弱化为相对/中性表达（删除"最/第一/顶级"等修饰或替换为"较/很/前列"），具体逐条替换值迁移前由产品统一确认。下表给出建议值。

**含"最"（PDF-A + PDF-B 类型三 + 通用1）**

| word | 建议 safe_word | severity |
|---|---|---|
| 最 | 较 | medium |
| 最佳 | 较好 | medium |
| 最具 | 较具 | medium |
| 最爱 | 深受喜爱 | medium |
| 最赚 | 划算 | medium |
| 最优 | 较优 | medium |
| 最优秀 | 较优秀 | medium |
| 最好 | 很好 | medium |
| 最大 | 较大 | medium |
| 最大程度 | 很大程度 | medium |
| 最高 | 很高 | medium |
| 最高级 | 高级 | medium |
| 最高档 | 高档 | medium |
| 最高端 | 高端 | medium |
| 最奢侈 | 较奢华 | medium |
| 最低 | 较低 | medium |
| 最低级 | 入门级 | medium |
| 最低价 | 优惠价 | medium |
| 最底 | 较低 | medium |
| 最便宜 | 实惠 | medium |
| 史上最低价 | 实惠价 | high |
| 时尚最低价 | 实惠价 | high |
| 最流行 | 流行 | medium |
| 最受欢迎 | 受欢迎 | medium |
| 最时尚 | 时尚 | medium |
| 最聚拢 | 聚拢 | medium |
| 最符合 | 很符合 | medium |
| 最舒适 | 很舒适 | medium |
| 最先 | 率先 | medium |
| 最先进 | 先进 | medium |
| 最先进科学 | 先进技术 | medium |
| 最先进加工工艺 | 先进工艺 | medium |
| 最先享受 | 优先体验 | medium |
| 最后 | XX | medium |
| 最后一波 | 本批 | high |
| 最新 | 新 | medium |
| 最新科技 | 新科技 | medium |
| 最新科学 | 新技术 | medium |
| 最新技术 | 新技术 | medium |

**含"一"（PDF-B 类型四 + 通用2）**

| word | 建议 safe_word | severity |
|---|---|---|
| 第一 | 前列 | medium |
| 中国第一 | 国内前列 | high |
| 全网第一 | 全网前列 | high |
| 销量第一 | 销量领先 | high |
| 排名第一 | 排名靠前 | medium |
| 唯一 | 少有 | medium |
| 第一品牌 | 头部品牌 | medium |
| NO.1 | 名列前茅 | medium |
| TOP1 | 名列前茅 | medium |
| 独一无二 | 别具特色 | medium |
| 全国第一 | 全国前列 | high |
| 一流 | 上乘 | medium |
| 仅此一次 | 限时 | high |
| 全国X大品牌之一 | 知名品牌之一 | medium |
| 销冠 | 热销 | medium |

**含"级/极"（PDF-B 类型五 + 通用3/4）**

| word | 建议 safe_word | severity |
|---|---|---|
| 国家级 | XX | high |
| 国际级 | XX | high |
| 全球级 | XX | high |
| 宇宙级 | XX | high |
| 世界级 | XX | high |
| 千万级 | XX | medium |
| 百万级 | XX | medium |
| 星级 | XX | medium |
| 甲级 | XX | medium |
| 超甲级 | XX | medium |
| 顶级 | 高端 | medium |
| 顶尖 | 前沿 | medium |
| 尖端 | 前沿 | medium |
| 顶级工艺 | 精良工艺 | medium |
| 顶级享受 | 优质体验 | medium |
| 高级 | 中高端 | medium |
| 极品 | 上乘 | medium |
| 极佳 | 很好 | medium |
| 绝佳 | 很好 | medium |
| 终极 | XX | medium |
| 极致 | 出色 | medium |
| 致极 | 出色 | medium |
| 极具 | 很有 | medium |

**极限/无法考证（PDF-B 类型六 + 通用4/5/6/9/10/11）**

| word | 建议 safe_word | severity |
|---|---|---|
| 绝对值 | XX | high |
| 绝对 | XX | high |
| 大牌 | 知名品牌 | medium |
| 精确 | XX | medium |
| 超赚 | 划算 | high |
| 领导品牌 | 头部品牌 | high |
| 领先上市 | 首批上市 | high |
| 巨星 | XX | medium |
| 著名 | 知名 | medium |
| 奢侈 | 奢华 | medium |
| 世界领先 | 行业前列 | high |
| 遥遥领先 | 行业前列 | high |
| 金牌 | XX | medium |
| 名牌 | 知名品牌 | medium |
| 优秀 | XX | low |
| 王牌 | XX | medium |
| 销量冠军 | 热销 | high |
| 永久 | XX | medium |
| 掌门人 | XX | medium |
| 领袖品牌 | 头部品牌 | high |
| 领袖 | XX | medium |
| 领导者 | XX | medium |
| 引领 | 带动 | low |
| 创领 | 创新 | low |
| 领航 | 先行 | low |
| 耀领 | 引领 | low |
| 绝无仅有 | 少见 | medium |
| 史无前例 | XX | high |
| 前无古人 | XX | high |
| 前无古人后无来者 | XX | high |
| 万能 | XX | medium |
| 百分之百 | XX | medium |
| 100% | XX | medium |
| 国际品质 | 优质 | medium |
| 高档 | 中高端 | medium |
| 正品 | XX | low |
| 至尊 | XX | medium |
| 至臻 | 臻品 | medium |
| 臻品 | 精品 | medium |
| 臻致 | 精致 | medium |
| 臻席 | 席位 | medium |
| 压轴 | XX | medium |
| 问鼎 | XX | medium |
| 空前 | XX | medium |
| 绝后 | XX | medium |
| 绝版 | 限量 | medium |
| 无双 | XX | medium |
| 非此莫属 | XX | medium |
| 前所未有 | XX | medium |
| 无人能及 | XX | medium |
| 鼎级 | 高端 | medium |
| 鼎冠 | XX | medium |
| 定鼎 | XX | medium |
| 翘楚之作 | 佳作 | medium |
| 不可再生 | XX | medium |
| 无与伦比 | 出众 | medium |
| 卓越 | 出色 | low |
| 卓著 | 出色 | low |
| 珍稀 | 稀少 | medium |
| 臻稀 | 稀少 | medium |
| 稀少 | XX | low |
| 稀世珍宝 | XX | medium |
| 千金难求 | XX | medium |
| 世所罕见 | XX | medium |
| 不可多得 | 难得 | medium |
| 空前绝后 | XX | medium |
| 屈指可数 | 为数不多 | medium |
| 冠军 | XX | medium |
| 王者 | XX | medium |
| 顶尖 | 前沿 | medium |

### 4.5 涉政 / 权威 / 国家敏感（→ `state_sensitive_words`）

来源：PDF-A「3.违反国家法律法规」「6.违反社会秩序」、PDF-B 类型一、通用 7/12、严重违规（涉政敏感）、其他敏感词 8

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 国家领导人 | XX | critical | PDF-B 严重违规 |
| 领导人 | XX | critical | PDF-B 严重违规 |
| 领导 | XX | critical | PDF-B 严重违规 |
| 行政机关 | XX | critical | PDF-B 严重违规 |
| 处级干部 | XX | critical | PDF-B 严重违规 |
| 警察 | XX | critical | PDF-B 严重违规 |
| 交警 | XX | critical | PDF-B 严重违规 |
| 国徽 | XX | critical | PDF-B 严重违规 |
| 国旗 | XX | critical | PDF-B 严重违规 |
| 党徽 | XX | critical | PDF-B 严重违规 |
| 国家领导人画像 | XX | critical | PDF-B 严重违规 |
| 社会主义核心价值观 | XX | critical | PDF-B 严重违规 |
| 邪教 | XX | critical | PDF-B 严重违规 |
| 非法宗教 | XX | critical | PDF-B 严重违规 |
| 交通管制 | XX | high | PDF-B 严重违规 |
| 政策原因 | XX | high | PDF-B 严重违规 |
| 政务 | XX | high | PDF-A 6 |
| 政府 | XX | high | PDF-A 6 |
| 国家免检 | XX | high | PDF-B 类型二 |
| 国家级产品 | XX | high | PDF-B 类型二 |
| 特供 | XX | high | PDF-B 类型一/12 |
| 专供 | XX | high | PDF-B 类型一/12 |
| 专家推荐 | 专业推荐 | medium | PDF-B 通用12 |
| 人民币图样 | XX | high | PDF-B 通用12 |
| 老字号 | 老品牌 | medium | PDF-B 类型一 |
| 中国驰名商标 | XX | high | PDF-B 类型一 |
| 质量免检 | XX | high | PDF-B 类型一 |
| 填补国内空白 | XX | high | PDF-B 类型二/通用7 |
| 开门红 | XX | medium | PDF-B 3.3 |
| 火热开抢 | XX | medium | PDF-B 3.3 |
| 庆祝 | XX | low | PDF-B 3.3 |
| 狂欢 | XX | low | PDF-B 3.3 |
| 疫情 | XX | medium | PDF-B 其他敏感词1 |
| 防疫补贴 | XX | high | PDF-B 其他敏感词1 |
| 抗疫英雄 | XX | medium | PDF-B 其他敏感词1 |
| 医护人员 | XX | low | PDF-B 其他敏感词1 |
| 志愿者 | XX | low | PDF-B 其他敏感词1 |
| 社区工作者 | XX | low | PDF-B 其他敏感词1 |
| 网红 | XX | low | PDF-B 其他敏感词1 |
| 明星 | XX | low | PDF-B 其他敏感词1 |
| 行政用车 | XX | high | PDF-B 严重违规（示例语） |
| 处级领导用的 | XX | critical | PDF-B 严重违规（示例语） |

> 注：涉政类词条以"XX"占位替换，实际替换词建议空/删除（此类词不建议出现在回复中），迁移时由产品确认。

### 4.6 诱导 / 欺诈 / 限时消费（→ `inducement_fraud_words`）

来源：PDF-A「2.利益诱导」「诱导互动」、PDF-B 通用13、其他敏感词 6/7、利益诱导

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 点击领奖 | 参与活动 | high | PDF-B 类型九/通用13 |
| 恭喜获奖 | 恭喜参与 | high | PDF-B 类型九/通用13 |
| 全民免单 | XX | high | PDF-B 类型九/通用13 |
| 点击有惊喜 | XX | medium | PDF-B 类型九/通用13 |
| 点击获取 | XX | medium | PDF-B 类型九/通用13 |
| 点击转身 | XX | medium | PDF-B 类型九/通用13 |
| 点击试穿 | XX | medium | PDF-B 类型九/通用13 |
| 点击翻转 | XX | medium | PDF-B 类型九/通用13 |
| 领取奖品 | 参与抽奖 | high | PDF-B 类型九/通用13 |
| 非转基因更安全 | XX | high | PDF-B 类型九 |
| 售罄 | 已售完 | low | PDF-B 通用13 |
| 售空 | 已售完 | low | PDF-B 通用13 |
| 再不抢就没了 | 库存有限 | high | PDF-B 通用13/其他敏感词6 |
| 不会再便宜 | 价格已优惠 | high | PDF-B 其他敏感词6 |
| 不会再便宜了 | 价格已优惠 | high | PDF-B 其他敏感词6 |
| 错过不再 | 机会有限 | high | PDF-B 通用13 |
| 错过即无 | 机会有限 | high | PDF-B 通用13 |
| 错过就没机会了 | 机会有限 | high | PDF-B 通用13 |
| 未曾有过的 | XX | medium | PDF-B 通用13 |
| 万人疯抢 | 热销 | high | PDF-B 通用13/其他敏感词6 |
| 全民疯抢 | 热销 | high | PDF-B 通用13 |
| 抢疯了 | 热销 | high | PDF-B 其他敏感词6 |
| 抢购 | 选购 | high | PDF-B 通用13 |
| 抢爆 | 热销 | high | PDF-B 其他敏感词6 |
| 秒杀 | 限时优惠 | high | PDF-B 其他敏感词6/利益诱导 |
| 秒杀价 | 优惠价 | high | PDF-B 利益诱导 |
| 跳楼价 | 优惠价 | high | PDF-B 利益诱导 |
| 超大福利 | 福利 | high | PDF-B 利益诱导 |
| 免费领 | 福利 | high | PDF-B 通用13 |
| 免费住 | XX | medium | PDF-B 通用13 |
| 零距离 | XX | medium | PDF-B 通用13 |
| 价格你来定 | XX | medium | PDF-B 通用13 |
| 抽奖 | 互动活动 | high | PDF-B 通用13/短视频标题雷区 |
| 打赏 | XX | high | PDF-B 短视频标题雷区 |
| 发红包 | XX | high | PDF-B 短视频标题雷区 |
| 倒计时 | XX | low | PDF-B 通用25 |
| 趁现在 | 现在 | low | PDF-B 通用25 |
| 仅限 | 限量 | medium | PDF-B 通用25 |
| 随时结束 | XX | high | PDF-B 通用25/其他敏感词7 |
| 随时涨价 | XX | high | PDF-B 通用25/其他敏感词7 |
| 马上降价 | XX | high | PDF-B 通用25/其他敏感词7 |
| 特惠趴 | 特惠活动 | medium | PDF-B 通用25 |
| 购物大趴 | 购物活动 | medium | PDF-B 通用25 |
| 闪购 | 限时购 | medium | PDF-B 通用25 |
| 今天错过 | XX | high | PDF-B 3.5 |
| 明天就没有这个优惠了 | XX | high | PDF-B 3.5（话术向） |

### 4.7 线下引流 / 联系方式引导（→ `contact_guidance_words`）

来源：PDF-A「4.线下诱导」「评论区」「私信」、PDF-B 线下引流违规、引导用户私下交易

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 微信 | 绿泡泡 | critical | PDF-A 3/评论区 / PDF-B 线下引流（沿用现有惯例） |
| 加微信 | 加绿泡泡 | critical | PDF-A 私信 / PDF-B 线下引流 |
| 微信号 | 绿泡泡号 | critical | PDF-B 线下引流（沿用惯例） |
| 加我 | 联系我 | critical | PDF-A 私信 |
| 我加你 | 我联系您 | critical | PDF-A 私信 |
| 微信截图 | XX | critical | PDF-A 3 |
| 二维码 | 小风车 | critical | PDF-B 线下引流 |
| 扫二维码 | 点击小风车 | critical | PDF-B 线下引流 |
| 电话号码 | 联系方式 | critical | PDF-A 4/评论区 / PDF-B 线下引流（沿用惯例） |
| 手机号 | 联系方式 | critical | PDF-A 4 / PDF-B 线下引流（沿用惯例） |
| 电话 | 联系方式 | high | PDF-A 4 |
| V | 绿泡泡 | critical | PDF-A 评论区 / PDF-B 线下引流（"加主播V"语境） |
| 加主播 | 点击小风车 | critical | PDF-B 线下引流 |
| 私下聊 | 详聊 | critical | PDF-B 引导私下交易 |
| 私下交易 | XX | critical | PDF-B 3.5/引导私下交易 |
| 私下销售 | XX | critical | PDF-B 3.5 |
| 绕过平台 | XX | critical | PDF-B 3.5 |
| 后台 | 客服 | high | PDF-A 评论区 |
| 私域 | XX | high | PDF-A 私信（话术向） |
| 留联系方式 | XX | high | PDF-A 私信（话术向） |
| 小红书 | XX | high | PDF-B 提及其他品牌/平台 |
| 快手 | XX | high | PDF-B 提及其他品牌/平台 |
| 报价 | 价格参考 | high | PDF-B 违规售卖 |
| 优惠 | 福利 | medium | PDF-B 违规售卖 |

> 注：单字"V"匹配面宽，建议迁移时评估误伤（如"VIP/SUV"等含 V 词），必要时启用词边界或改词条为"加V/主播V"。

### 4.8 迷信用语（→ `superstition_words`）

来源：PDF-B 类型七、通用18、直播间负面（吸烟赌博）

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 招财 | XX | medium | PDF-B 直播间负面 |
| 好运 | XX | medium | PDF-B 直播间负面 |
| 算命 | XX | medium | PDF-B 直播间负面 |
| 招财进宝 | XX | medium | PDF-B 类型七 |
| 健康富贵 | XX | medium | PDF-B 类型七 |
| 提升运气 | XX | medium | PDF-B 类型七 |
| 有助事业 | XX | medium | PDF-B 类型七 |
| 护身 | XX | medium | PDF-B 类型七 |
| 平衡正负能量 | XX | medium | PDF-B 类型七 |
| 消除精神压力 | XX | medium | PDF-B 类型七 |
| 调和气压 | XX | medium | PDF-B 类型七 |
| 逢凶化吉 | XX | medium | PDF-B 类型七 |
| 时来运转 | XX | medium | PDF-B 类型七 |
| 万事亨通 | XX | medium | PDF-B 类型七 |
| 旺人 | XX | medium | PDF-B 类型七 |
| 旺财 | XX | medium | PDF-B 类型七 |
| 助吉避凶 | XX | medium | PDF-B 类型七 |
| 转富招福 | XX | medium | PDF-B 类型七 |

### 4.9 不文明 / 歧视用语（→ `incivility_words`）

来源：PDF-B 3.10、违反公序良俗

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 黑鬼 | XX | critical | PDF-B 3.10 |
| 尼哥 | XX | critical | PDF-B 3.10 |
| 杂种 | XX | critical | PDF-B 3.10 |
| 东亚病夫 | XX | critical | PDF-B 3.10 |
| 小日本 | XX | critical | PDF-B 3.10 |
| 大男子主义 | XX | medium | PDF-B 3.10 |
| 普信男 | XX | medium | PDF-B 3.10/公序良俗 |
| 单身狗 | XX | medium | PDF-B 公序良俗 |
| 瞎逼逼 | XX | critical | PDF-B 公序良俗 |
| 垃圾 | XX | medium | PDF-B 3.4（贬低竞品语境） |

### 4.10 版权 / 赛事 / IP（→ `ip_event_words`）

来源：PDF-B 3.2、通用20、活动类

| word | 建议 safe_word | severity | 来源 |
|---|---|---|---|
| 世界杯 | XX | high | PDF-B 3.2/通用20 |
| 冬奥会 | XX | high | PDF-B 3.2/通用20 |
| 奥林匹克运动会 | XX | high | PDF-B 3.2/通用20 |
| 双十一 | XX | medium | PDF-B 通用20 |
| 双十二 | XX | medium | PDF-B 通用20 |
| 米老鼠 | XX | medium | PDF-B 3.2 |
| 马里奥 | XX | medium | PDF-B 3.2 |
| 吉祥物 | XX | medium | PDF-B 3.2 |
| IP形象 | XX | medium | PDF-B 3.2 |

## 5. 迁移实现要点

1. **幂等**：`(library_id, word)` 唯一，迁移脚本需 `WHERE NOT EXISTS` 或 `ON CONFLICT` 防重。
2. **词库幂等**：新 7 个 library_key 按 `forbidden_word_libraries` 现有 seed 模式（`WHERE NOT EXISTS`）插入。
3. **safe_word 为兼容可选字段（G1-DELTA 后不再必填、不参与替换）**：`safe_word` 留空不影响词条生效（仍进入 LLM 检查与检测）；涉政类等"禁止出现"词条可安全留空。
4. **单字/宽匹配评估**：单字"改"、"V"、"最"等匹配面宽，迁移时评估是否启用词边界/组合词条，避免误伤。
5. **LLM 提示词联动**：`load_forbidden_words_for_llm` 会注入全局活跃词供 LLM 规避（禁止语义），新词条入库后 LLM 侧自动生效，无需额外改造。
6. **命中日志**：新词条命中自动写 `forbidden_word_hit_logs`（检测/审计路径）或 `manual_required=forbidden_word_hit`（LLM 生成后检查路径），可在运营后台观测命中分布，反向校验词库质量。
7. **作用范围差异（G1-DELTA 冻结）**：LLM 路径（禁止+重生成 1 次+仍命中转人工）覆盖抖音 AI 客服自动回复；微信派单/通知/反馈完全豁免抖音违禁词；抖音人工私信原文发送；抖音自动回访话术发送前检测命中阻断；回访模板命中 400 拒绝保存。

## 6. 后续动作

- [ ] 甲方/产品对 `safe_word` 建议值确认——`safe_word` 现为兼容可选字段（不参与替换、不再必填），涉政类词条可留空
- [ ] 编写数据库迁移（基于本清单，建议在 `migrations/` 下新增版本）
- [ ] 迁移后抽样测试检测效果（可复用 `tests/test_forbidden_word_service.py` / `tests/test_forbidden_word_policy.py` 模式）与 LLM 生成后检查命中转人工/重生成行为
- [ ] 观察 `forbidden_word_hit_logs` / `manual_required=forbidden_word_hit` 命中数据，迭代词库

---

## 附录 A：提取过程说明

- 工具：`pdftotext`（poppler）+ `pymupdf`（Python 3.14），规避模型直接读取 PDF 导致的 400 错误。
- PDF-B 部分字体（KaiTi/GBK-EUC-H CMap）提取有乱码，已通过 PyMuPDF 二次提取核对。
- 乱码词汇（约 25 项）按甲方决策 B 直接忽略，未列入词库。
- 全文词条提取自 PDF-A 3 页 + PDF-B 11 页，覆盖"违规词总结 / 通用敏感词 / 直播间违规情况整理 / 短视频违规事项"四个部分中与汽车直播强相关章节。

## 附录 B：源文件索引

- `E:\work\project\project_info\Project_autowechat\直播违规注意事项.pdf`
- `E:\work\project\project_info\Project_autowechat\抖音汽车直播违禁词规避及辟谣指南.pdf`
- 提取文本暂存：`E:\tmp\wg01_m.txt` / `E:\tmp\wg02_m.txt`
