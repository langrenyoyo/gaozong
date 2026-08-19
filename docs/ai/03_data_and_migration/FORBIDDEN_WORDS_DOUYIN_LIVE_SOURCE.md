# 抖音汽车直播违禁词库 —— 迁移依据文档（来源：甲方两份 PDF）

> 状态：**词条已确认，可作数据库迁移依据**
> 日期：2026-08-19（G1-DELTA 冻结方案后更新：违禁词只检测/审计，不再替换；**safe_word 已取消**）
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
| A. 明确违禁词清单 | **全部纳入** |
| B. 疑似 OCR 乱码 / 错字词汇 | **直接忽略，不纳入** |
| C. 行为 / 场景描述类（非具体词汇） | **直接跳过，不转化为词条** |
| 覆盖范围 | **只保留与汽车、直播强相关的类别**，剔除房地产/教育/户口/无预售许可证等弱相关词条 |
| safe_word | **取消**（2026-08-19 复核：检测模式不需要替换词，词条不再填写 safe_word） |

### 2.1 被剔除的内容（明确不纳入）

- **乱码词汇**：市米好运增虫弟怒、最聚找、最峰、透留、独据、首迹、顾地、层晓、这这无几、绝不在有、不可女制、股堂、升值洪力无线、买到即嫌到、亚禁使用、违宗词、精丁德式装修、干X宏的歌、算一第二、金融汇币图片 等（共 25 项，详见提取过程记录，此处从略）。
- **行为/场景描述**：踩一捧一、衣着暴露/聚焦敏感部位、危险行为、挂机录播、展示微信截图、提及其他汽车品牌、福袋抽实物奖品、引导私下交易、招聘/招生/招商、恶意爱国营销、方言/连读误判 等——**不转词条**。
- **房地产/教育/户口等弱相关词条**：得房率、绿化率、容积率、CBD 坐标、地铁上盖、咫尺地铁站、万亩公园、学区房、承诺户口、蓝印户口、九年制教育、无预售许可证、楼王、墅王、黄金旺铺、黄金地段、寸土寸金、上风上水、龙脉之地、堪舆 等。
- **文字/肖像权类弱相关**：外国文字、毛笔字、繁体字、无版权字体、公民肖像权、儿童肖像权、明星肖像权、名人肖像权 等。

## 3. 目标数据库结构对接

落库表结构（现有，`migrations/versions/0027_xiaogao_phase1_core.sql` / `app/models.py`）：

- `forbidden_word_libraries`：`library_key`(唯一)、`name`、`description`、`scope='global'`、`enabled=1`
- `forbidden_words`：`library_id`、`word`、`safe_word`(兼容可选，**本词库全部留空**)、`severity`、`enabled=1`；`(library_id, word)` 唯一

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

**`safe_word` 已取消（2026-08-19 复核确认）**
- `forbidden_word_service._load_active_words` 不再过滤 `safe_word`，空 `safe_word` 词条**仍进入 LLM 检查与检测**
- 前端 `SuperForbiddenWords.tsx` 已移除安全替换词录入/展示/必填校验
- 固定敏感词替换 `_replace_sensitive_words`（微信→绿泡泡、手机号→联系方式、个人号→v）已删除
- **本词库所有词条 `safe_word` 一律留空（NULL），不做任何替换**

### 3.1 词库规划（library_key）

现有 3 库直接复用，新增 7 库：

| library_key | 名称 | 复用/新增 | 来源类别 |
|---|---|---|---|
| `used_car_sales_base` | 二手车销售基础违禁词 | 复用 | 汽车行业特有（违规售卖） |
| `finance_compliance` | 金融方案合规词库 | 复用 | 金融相关 |
| `vehicle_condition_risk` | 车况承诺风险词 | 复用 | 车况承诺风险 |
| `extreme_ad_words` | 极限用语/绝对化用语 | 新增 | 最/一/级/极/首/家/国/极限无法考证 |
| `state_sensitive_words` | 涉政/权威/国家敏感词 | 新增 | 权威国家、涉政敏感 |
| `inducement_fraud_words` | 诱导/欺诈/限时消费词 | 新增 | 诱导欺诈、利益诱导、刺激消费、时限用语 |
| `contact_guidance_words` | 线下引流/联系方式引导词 | 新增 | 线下引流、私域引导 |
| `superstition_words` | 迷信用语 | 新增 | 迷信、直播间负面（招财好运算命） |
| `incivility_words` | 不文明/歧视用语 | 新增 | 不文明用语、歧视、血腥暴力、负面 |
| `ip_event_words` | 版权/赛事/IP 词 | 新增 | 赛事营销、未授权 IP |

> 说明：以上 library_key 为建议值，迁移实现时可按需调整；词条归属以第 4 节表格为准。

## 4. 违禁词条清单（已确认，safe_word 全部留空）

> **`safe_word` 一律留空（NULL）**：检测模式不需要替换词，空 `safe_word` 词条仍进入 LLM 检查与检测（G1-DELTA 已确认）。
> `severity` 取值建议：`critical`（涉政/联系方式/金融）/ `high` / `medium` / `low`。
> 来源标注：PDF-A=《直播违规注意事项》章节号，PDF-B=《抖音汽车直播违禁词规避及辟谣指南》章节号。

### 4.1 汽车行业特有 —— 违规售卖二手车（→ `used_car_sales_base`）

来源：PDF-A「1.违规售卖二手车」、PDF-B「违规售卖/不接受投放」

| word | severity | 来源 |
|---|---|---|
| 故事车 | high | PDF-A 1 |
| 事故车 | high | PDF-A 1 |
| 瑕疵 | medium | PDF-A 1 |
| 改装 | high | PDF-A 1 / PDF-B 不接受投放 |
| 报废 | high | PDF-A 1 |
| 抵押车 | high | PDF-A 1 |
| 换件 | high | PDF-A 1 |
| 过不了户 | critical | PDF-A 1 |
| 收车 | high | PDF-A 1 |
| 回收 | high | PDF-A 1 |
| 二手车回收 | high | PDF-B 不接受投放 |
| 加装 | medium | PDF-A 1 |
| 升级 | medium | PDF-A 1 |
| 改款 | medium | PDF-A 1 |
| 车衣 | medium | PDF-A 1 |
| 贴膜 | medium | PDF-A 1 / PDF-B 不接受投放 |
| 车膜 | medium | PDF-B 不接受投放 |
| 车贴 | medium | PDF-B 不接受投放 |
| 轮毂 | medium | PDF-B 不接受投放（改装语境） |
| 购置税 | high | PDF-B 不接受投放二 |
| 购置税全免 | high | PDF-B 不接受投放二 |
| 卖车 | high | PDF-B 违规售卖（未挂小风车时） |

> 注：PDF-B 明确"只提及'改'字也会触发违规"，单字"改"作为高危词建议单独评估是否入库（涉及"改款/改装/改车"等组合），迁移时由产品确认。

### 4.2 金融相关（→ `finance_compliance`）

来源：PDF-A「5.金融相关（小雪花）」、PDF-B 通用敏感词「21.价值」「27.其他」

| word | severity | 来源 |
|---|---|---|
| 分期 | high | PDF-A 5 |
| 贷款 | high | PDF-A 5 / PDF-B 27 |
| 置换 | high | PDF-A 5 |
| 抵押 | high | PDF-A 5 |
| 征信 | high | PDF-A 5 |
| 按揭 | high | PDF-A 5 |
| 黑户 | critical | PDF-A 5/6 / PDF-B 3.1 |
| 金融 | high | PDF-A 5 |
| 首付 | high | PDF-A 5 / PDF-B 通用13 |
| 利息 | high | PDF-A 5 |
| 利率 | high | PDF-A 5 |
| 免息 | high | PDF-A 5 / PDF-B 3.5 |
| 0首付 | critical | PDF-B 通用13 |
| 免首付 | critical | PDF-B 通用13 |
| 投资回报 | medium | PDF-B 通用21 |
| 众筹 | high | PDF-B 通用21 |
| 千亿价值 | high | PDF-B 通用21 |
| 价值洼地 | medium | PDF-B 通用21 |
| 价值天成 | medium | PDF-B 通用21 |
| 抄涨 | high | PDF-B 通用21 |
| 炒股不如买房 | high | PDF-B 通用21（话术向，可评估） |

### 4.3 车况承诺风险（→ `vehicle_condition_risk`）

来源：PDF-A「1.违规售卖二手车」、PDF-B「类型八 虚假内容」

| word | severity | 来源 |
|---|---|---|
| 纯天然 | medium | PDF-B 类型八 |
| 祖传 | medium | PDF-B 类型八 |
| 特效 | medium | PDF-B 类型八 |
| 无敌 | medium | PDF-B 类型八 |
| 质量免检 | high | PDF-B 类型一 |
| 无需国家质量检测 | high | PDF-B 类型一 |
| 免抽检 | high | PDF-B 类型一 |
| 样板间实景图 | low | PDF-B 通用27 |
| 效果图 | low | PDF-B 通用27 |

### 4.4 极限用语 / 绝对化用语（→ `extreme_ad_words`）

> 覆盖来源：PDF-A「严禁使用极限用语」、PDF-B 类型二/三/四/五/六、通用敏感词 1/2/3/4/5/6/7/9/10/11/27、其他敏感词 2/3/4。
> 纯检测模式：词条只用于检测/LLM 规避，不替换正文。

**含"最"（PDF-A + PDF-B 类型三 + 通用1）**

> 注：单字符"最"（2026-08-19 迁移决策：**不入库**，`len(strip(word))==1` 规则排除），多字符"最佳/最好/最大"等正常入库。

| word | severity |
|---|---|
| 最 | medium |
| 最佳 | medium |
| 最具 | medium |
| 最爱 | medium |
| 最赚 | medium |
| 最优 | medium |
| 最优秀 | medium |
| 最好 | medium |
| 最大 | medium |
| 最大程度 | medium |
| 最高 | medium |
| 最高级 | medium |
| 最高档 | medium |
| 最高端 | medium |
| 最奢侈 | medium |
| 最低 | medium |
| 最低级 | medium |
| 最低价 | medium |
| 最底 | medium |
| 最便宜 | medium |
| 史上最低价 | high |
| 时尚最低价 | high |
| 最流行 | medium |
| 最受欢迎 | medium |
| 最时尚 | medium |
| 最聚拢 | medium |
| 最符合 | medium |
| 最舒适 | medium |
| 最先 | medium |
| 最先进 | medium |
| 最先进科学 | medium |
| 最先进加工工艺 | medium |
| 最先享受 | medium |
| 最后 | medium |
| 最后一波 | high |
| 最新 | medium |
| 最新科技 | medium |
| 最新科学 | medium |
| 最新技术 | medium |

**含"一"（PDF-B 类型四 + 通用2）**

| word | severity |
|---|---|
| 第一 | medium |
| 中国第一 | high |
| 全网第一 | high |
| 销量第一 | high |
| 排名第一 | medium |
| 唯一 | medium |
| 第一品牌 | medium |
| NO.1 | medium |
| TOP1 | medium |
| 独一无二 | medium |
| 全国第一 | high |
| 一流 | medium |
| 一天 | medium |
| 仅此一次 | high |
| 全国X大品牌之一 | medium |
| 销冠 | medium |

**含"级/极"（PDF-B 类型五 + 通用3/4）**

| word | severity |
|---|---|
| 国家级 | high |
| 国际级 | high |
| 全球级 | high |
| 宇宙级 | high |
| 世界级 | high |
| 千万级 | medium |
| 百万级 | medium |
| 星级 | medium |
| 甲级 | medium |
| 超甲级 | medium |
| 顶级 | medium |
| 顶尖 | medium |
| 尖端 | medium |
| 顶级工艺 | medium |
| 顶级享受 | medium |
| 高级 | medium |
| 极品 | medium |
| 极佳 | medium |
| 绝佳 | medium |
| 终极 | medium |
| 极致 | medium |
| 致极 | medium |
| 极具 | medium |

**含"首/家/国"（PDF-B 类型二 + 通用7）**

| word | severity |
|---|---|
| 首个 | medium |
| 首选 | medium |
| 全球首发 | high |
| 全国首家 | high |
| 全网首发 | high |
| 首款 | medium |
| 首家 | medium |
| 独家 | medium |
| 独家配方 | medium |
| 首发 | medium |
| 首席 | medium |
| 首府 | medium |
| 首屈一指 | medium |
| 首次 | medium |
| 全国销量冠军 | high |
| 填补国内空白 | high |

**独家 / 缔造类（PDF-B 通用6）**

| word | severity |
|---|---|
| 独创 | medium |
| 开发者 | medium |
| 缔造者 | medium |
| 创始者 | medium |
| 发明者 | medium |

**极限/无法考证（PDF-B 类型六 + 通用4/5/9/10/11/27）**

| word | severity |
|---|---|
| 绝对值 | high |
| 绝对 | high |
| 大牌 | medium |
| 精确 | medium |
| 超赚 | high |
| 领导品牌 | high |
| 领先上市 | high |
| 巨星 | medium |
| 著名 | medium |
| 奢侈 | medium |
| 世界领先 | high |
| 遥遥领先 | high |
| 金牌 | medium |
| 名牌 | medium |
| 优秀 | low |
| 王牌 | medium |
| 销量冠军 | high |
| 永久 | medium |
| 掌门人 | medium |
| 领袖品牌 | high |
| 领袖 | medium |
| 领导者 | medium |
| 引领 | low |
| 创领 | low |
| 领航 | low |
| 耀领 | low |
| 绝无仅有 | medium |
| 史无前例 | high |
| 前无古人 | high |
| 前无古人后无来者 | high |
| 万能 | medium |
| 百分之百 | medium |
| 100% | medium |
| 国际品质 | medium |
| 高档 | medium |
| 正品 | low |
| 至尊 | medium |
| 至臻 | medium |
| 臻品 | medium |
| 臻致 | medium |
| 臻席 | medium |
| 压轴 | medium |
| 问鼎 | medium |
| 空前 | medium |
| 绝后 | medium |
| 绝版 | medium |
| 无双 | medium |
| 非此莫属 | medium |
| 前所未有 | medium |
| 无人能及 | medium |
| 鼎级 | medium |
| 鼎冠 | medium |
| 定鼎 | medium |
| 翘楚之作 | medium |
| 不可再生 | medium |
| 无与伦比 | medium |
| 卓越 | low |
| 卓著 | low |
| 完美 | medium |
| 淋漓尽致 | medium |
| 珍稀 | medium |
| 臻稀 | medium |
| 稀少 | low |
| 稀世珍宝 | medium |
| 千金难求 | medium |
| 世所罕见 | medium |
| 不可多得 | medium |
| 空前绝后 | medium |
| 屈指可数 | medium |
| 冠军 | medium |
| 王者 | medium |
| 三甲 | medium |
| 十强 | medium |

### 4.5 涉政 / 权威 / 国家敏感（→ `state_sensitive_words`）

来源：PDF-A「3.违反国家法律法规」「6.违反社会秩序」、PDF-B 类型一、通用 7/12/19/27、严重违规（涉政敏感）、其他敏感词 1/8

| word | severity | 来源 |
|---|---|---|
| 国家领导人 | critical | PDF-B 严重违规 |
| 领导人 | critical | PDF-B 严重违规 |
| 领导 | critical | PDF-B 严重违规 |
| 行政机关 | critical | PDF-B 严重违规 |
| 政府机关 | critical | PDF-B 通用19 |
| 处级干部 | critical | PDF-B 严重违规 |
| 警察 | critical | PDF-B 严重违规 |
| 交警 | critical | PDF-B 严重违规 |
| 国徽 | critical | PDF-B 严重违规 |
| 国旗 | critical | PDF-B 严重违规 |
| 国歌 | critical | PDF-B 通用27 |
| 党徽 | critical | PDF-B 严重违规 |
| 国家领导人画像 | critical | PDF-B 严重违规 |
| 社会主义核心价值观 | critical | PDF-B 严重违规 |
| 邪教 | critical | PDF-B 严重违规 |
| 非法宗教 | critical | PDF-B 严重违规 |
| 交通管制 | high | PDF-B 严重违规 |
| 政策原因 | high | PDF-B 严重违规 |
| 政务 | high | PDF-A 6 |
| 政府 | high | PDF-A 6 |
| 国家免检 | high | PDF-B 类型二 |
| 国家级产品 | high | PDF-B 类型二 |
| 特供 | high | PDF-B 类型一/12 |
| 专供 | high | PDF-B 类型一/12 |
| 专家推荐 | medium | PDF-B 通用12 |
| 人民币图样 | high | PDF-B 通用12 |
| 老字号 | medium | PDF-B 类型一 |
| 中国驰名商标 | high | PDF-B 类型一 |
| 开门红 | medium | PDF-B 3.3 |
| 火热开抢 | medium | PDF-B 3.3 |
| 庆祝 | low | PDF-B 3.3 |
| 狂欢 | low | PDF-B 3.3 |
| 疫情 | medium | PDF-B 其他敏感词1 |
| 防疫补贴 | high | PDF-B 其他敏感词1 |
| 抗疫英雄 | medium | PDF-B 其他敏感词1 |
| 医护人员 | low | PDF-B 其他敏感词1 |
| 志愿者 | low | PDF-B 其他敏感词1 |
| 社区工作者 | low | PDF-B 其他敏感词1 |
| 网红 | low | PDF-B 其他敏感词1 |
| 明星 | low | PDF-B 其他敏感词1 |
| 行政用车 | high | PDF-B 严重违规（示例语） |
| 处级领导用的 | critical | PDF-B 严重违规（示例语） |

> 注：涉政类词条在纯检测模式下 `safe_word` 留空即可（不做替换），命中即触发 LLM 重生成/转人工。

### 4.6 诱导 / 欺诈 / 限时消费（→ `inducement_fraud_words`）

来源：PDF-A「2.利益诱导」「诱导互动」「诱导交易」、PDF-B 类型九、通用13/25、其他敏感词 6/7、利益诱导

| word | severity | 来源 |
|---|---|---|
| 点击领奖 | high | PDF-B 类型九/通用13 |
| 恭喜获奖 | high | PDF-B 类型九/通用13 |
| 全民免单 | high | PDF-B 类型九/通用13 |
| 点击有惊喜 | medium | PDF-B 类型九/通用13 |
| 点击获取 | medium | PDF-B 类型九/通用13 |
| 点击转身 | medium | PDF-B 类型九/通用13 |
| 点击试穿 | medium | PDF-B 类型九/通用13 |
| 点击翻转 | medium | PDF-B 类型九/通用13 |
| 领取奖品 | high | PDF-B 类型九/通用13 |
| 非转基因更安全 | high | PDF-B 类型九 |
| 售罄 | low | PDF-B 通用13 |
| 售空 | low | PDF-B 通用13 |
| 再不抢就没了 | high | PDF-B 通用13/其他敏感词6 |
| 不会再便宜 | high | PDF-B 其他敏感词6 |
| 不会再便宜了 | high | PDF-B 其他敏感词6 |
| 错过不再 | high | PDF-B 通用13 |
| 错过即无 | high | PDF-B 通用13 |
| 错过就没机会了 | high | PDF-B 通用13 |
| 未曾有过的 | medium | PDF-B 通用13 |
| 万人疯抢 | high | PDF-B 通用13/其他敏感词6 |
| 全民疯抢 | high | PDF-B 通用13 |
| 抢疯了 | high | PDF-B 其他敏感词6 |
| 抢购 | high | PDF-B 通用13 |
| 抢爆 | high | PDF-B 其他敏感词6 |
| 秒杀 | high | PDF-B 其他敏感词6/利益诱导 |
| 秒杀价 | high | PDF-B 利益诱导 |
| 跳楼价 | high | PDF-B 利益诱导 |
| 超大福利 | high | PDF-B 利益诱导 |
| 免费领 | high | PDF-B 通用13 |
| 免费住 | medium | PDF-B 通用13 |
| 零距离 | medium | PDF-B 通用13 |
| 价格你来定 | medium | PDF-B 通用13 |
| 抽奖 | high | PDF-B 通用13/短视频标题雷区 |
| 打赏 | high | PDF-B 短视频标题雷区 |
| 发红包 | high | PDF-B 短视频标题雷区 |
| 金钱 | high | PDF-A 诱导交易 |
| 红包 | high | PDF-A 诱导交易 |
| 低价引流 | high | PDF-A 诱导交易 |
| 粉丝灯牌 | medium | PDF-A 利益诱导 |
| 灯牌 | medium | PDF-A 利益诱导 |
| 礼物 | medium | PDF-A 利益诱导 |
| 上飞机 | medium | PDF-A 利益诱导（抖音礼物名） |
| 保时捷墨镜 | medium | PDF-A 利益诱导（抖音礼物名） |
| 拍了 | medium | PDF-A 诱导互动 |
| 想要 | medium | PDF-A 诱导互动 |
| 666 | medium | PDF-A 诱导互动 |
| 报名 | medium | PDF-A 诱导互动 |
| 扣666 | medium | PDF-A 诱导互动（示例话术） |
| 倒计时 | low | PDF-B 通用25 |
| 趁现在 | low | PDF-B 通用25 |
| 仅限 | medium | PDF-B 通用25 |
| 随时结束 | high | PDF-B 通用25/其他敏感词7 |
| 随时涨价 | high | PDF-B 通用25/其他敏感词7 |
| 马上降价 | high | PDF-B 通用25/其他敏感词7 |
| 特惠趴 | medium | PDF-B 通用25 |
| 购物大趴 | medium | PDF-B 通用25 |
| 闪购 | medium | PDF-B 通用25 |
| 几天几夜 | medium | PDF-B 通用25 |
| 周年庆 | medium | PDF-B 通用25 |
| 品牌团 | medium | PDF-B 通用25 |
| 今天错过 | high | PDF-B 3.5 |
| 明天就没有这个优惠了 | high | PDF-B 3.5（话术向） |

> 注："礼物"、"666"、"报名" 等为诱导互动语境词，匹配面较宽，迁移时评估是否需组合词条（如"扣666"）降低误伤。

### 4.7 线下引流 / 联系方式引导（→ `contact_guidance_words`）

来源：PDF-A「4.线下诱导」「评论区」「私信」、PDF-B 线下引流违规、引导用户私下交易

| word | severity | 来源 |
|---|---|---|
| 微信 | critical | PDF-A 3/评论区 / PDF-B 线下引流 |
| 加微信 | critical | PDF-A 私信 / PDF-B 线下引流 |
| 微信号 | critical | PDF-B 线下引流 |
| 加我 | critical | PDF-A 私信 |
| 我加你 | critical | PDF-A 私信 |
| 微信截图 | critical | PDF-A 3 |
| 二维码 | critical | PDF-B 线下引流 |
| 扫二维码 | critical | PDF-B 线下引流 |
| 电话号码 | critical | PDF-A 4/评论区 / PDF-B 线下引流 |
| 手机号 | critical | PDF-A 4 / PDF-B 线下引流 |
| 电话 | high | PDF-A 4 |
| 地址 | critical | PDF-A 4/评论区/私信 |
| V | critical | PDF-A 评论区 / PDF-B 线下引流（"加主播V"语境） |
| 加主播 | critical | PDF-B 线下引流 |
| 私信主播 | critical | PDF-B 线下引流 |
| 私下聊 | critical | PDF-B 引导私下交易 |
| 私下交易 | critical | PDF-B 3.5/引导私下交易 |
| 私下销售 | critical | PDF-B 3.5 |
| 绕过平台 | critical | PDF-B 3.5 |
| qq | high | PDF-A 诱导交易 |
| QQ | high | PDF-A 诱导交易 |
| 后台 | high | PDF-A 评论区 |
| 私域 | high | PDF-A 私信（话术向） |
| 留联系方式 | high | PDF-A 私信（话术向） |
| 小红书 | high | PDF-B 提及其他品牌/平台 |
| 快手 | high | PDF-B 提及其他品牌/平台 |
| 报价 | high | PDF-B 违规售卖 |
| 优惠 | medium | PDF-B 违规售卖 |

> 注：单字"V"匹配面宽（如"VIP/SUV"等含 V 词），**2026-08-19 迁移决策：单字符词条"V"不入库**（`len(strip(word))==1` 规则排除），避免误伤。`qq` 与 `QQ` 按 casefold 视为重复，仅保留 `qq` 一个规范化词条。

### 4.8 迷信用语（→ `superstition_words`）

来源：PDF-B 类型七、通用18、直播间负面（吸烟赌博中的迷信部分）

| word | severity | 来源 |
|---|---|---|
| 招财 | medium | PDF-B 直播间负面 |
| 好运 | medium | PDF-B 直播间负面 |
| 算命 | medium | PDF-B 直播间负面 |
| 招财进宝 | medium | PDF-B 类型七 |
| 健康富贵 | medium | PDF-B 类型七 |
| 提升运气 | medium | PDF-B 类型七 |
| 有助事业 | medium | PDF-B 类型七 |
| 护身 | medium | PDF-B 类型七 |
| 平衡正负能量 | medium | PDF-B 类型七 |
| 消除精神压力 | medium | PDF-B 类型七 |
| 调和气压 | medium | PDF-B 类型七 |
| 逢凶化吉 | medium | PDF-B 类型七 |
| 时来运转 | medium | PDF-B 类型七 |
| 万事亨通 | medium | PDF-B 类型七 |
| 旺人 | medium | PDF-B 类型七 |
| 旺财 | medium | PDF-B 类型七 |
| 助吉避凶 | medium | PDF-B 类型七 |
| 转富招福 | medium | PDF-B 类型七 |

### 4.9 不文明 / 歧视 / 负面用语（→ `incivility_words`）

来源：PDF-B 3.10、通用21（歧视性词语）、违反公序良俗、直播间负面（吸烟赌博）、PDF-A 违反社会秩序

| word | severity | 来源 |
|---|---|---|
| 黑鬼 | critical | PDF-B 3.10 |
| 尼哥 | critical | PDF-B 3.10 |
| 杂种 | critical | PDF-B 3.10 |
| 东亚病夫 | critical | PDF-B 3.10 |
| 小日本 | critical | PDF-B 3.10 |
| 大男子主义 | medium | PDF-B 3.10 |
| 普信男 | medium | PDF-B 3.10/公序良俗 |
| 单身狗 | medium | PDF-B 公序良俗 |
| 瞎逼逼 | critical | PDF-B 公序良俗 |
| 垃圾 | medium | PDF-B 3.4（贬低竞品语境） |
| 贵族 | medium | PDF-B 通用21 |
| 高贵 | medium | PDF-B 通用21 |
| 上流 | medium | PDF-B 通用21 |
| 富人区 | medium | PDF-B 通用21 |
| 名门 | medium | PDF-B 通用21 |
| 阶层 | medium | PDF-B 通用21 |
| 阶级 | medium | PDF-B 通用21 |
| 血腥 | high | PDF-A 违反社会秩序 |
| 暴力 | high | PDF-A 违反社会秩序 |
| 赌博 | high | PDF-B 直播间负面 |
| 抽烟 | low | PDF-B 直播间负面 |
| 喝酒 | low | PDF-B 直播间负面 |

### 4.10 版权 / 赛事 / IP（→ `ip_event_words`）

来源：PDF-B 3.2、通用20、活动类

| word | severity | 来源 |
|---|---|---|
| 世界杯 | high | PDF-B 3.2/通用20 |
| 冬奥会 | high | PDF-B 3.2/通用20 |
| 奥林匹克运动会 | high | PDF-B 3.2/通用20 |
| 双十一 | medium | PDF-B 通用20 |
| 双十二 | medium | PDF-B 通用20 |
| 米老鼠 | medium | PDF-B 3.2 |
| 马里奥 | medium | PDF-B 3.2 |
| 吉祥物 | medium | PDF-B 3.2 |
| IP形象 | medium | PDF-B 3.2 |
| 公众人物形象 | medium | PDF-B 3.2 |

## 5. 迁移实现要点（2026-08-19 已实施）

**已落地迁移**：SQLite `migrations/versions/0047_forbidden_word_seed.sql` + PostgreSQL Alembic `migrations/postgres/auto_wechat/versions/0037_forbidden_word_seed.py`（down_revision=0036）。

1. **幂等**：`(library_id, word)` 唯一；SQLite 用 `WHERE NOT EXISTS`，PG 用 `ON CONFLICT DO NOTHING` 防重。
2. **词库幂等**：10 个 library_key（3 现有 + 7 新增）按 `WHERE NOT EXISTS` 插入，缺失才新增，不覆盖已有词库配置（scope=global）。
3. **safe_word 一律 NULL（已取消）**：本词库所有词条 `safe_word` 写入 SQL NULL，不做任何替换；空值不影响词条进入 LLM 检查与检测（G1-DELTA 后 `_load_active_words` 不再过滤 `safe_word`）。
4. **单字/宽匹配评估（已执行）**：**单字符词条全部不入库**——含"最"（extreme_ad_words）与"V"（contact_guidance_words）均被排除（`len(strip(word))==1` 规则）；"改"不在清单中；"666"为 3 字符词条正常入库（`扣666` 组合需依赖命中日志评估）。
5. **qq/QQ 去重（已执行）**：`qq` 与 `QQ` 按 casefold 视为重复，仅保留 1 个规范化词条 `qq`（contact_guidance_words）。
6. **最终写入 403 条**（原始 406 − 单字符"最""V"2 条 − qq/QQ 去重 1 条）。分布：used_car_sales_base=22、finance_compliance=21、vehicle_condition_risk=9、extreme_ad_words=171、state_sensitive_words=42、inducement_fraud_words=62、contact_guidance_words=26、superstition_words=18、incivility_words=22、ip_event_words=10。
7. **新词条 enabled=true；不覆盖已有词条运营状态**（迁移只插入缺失词条，不 UPDATE 已有 enabled/severity）。
8. **LLM 提示词联动**：`load_forbidden_words_for_llm` 会注入全局活跃词供 LLM 规避（禁止语义），新词条入库后 LLM 侧自动生效，无需额外改造。
9. **命中日志**：新词条命中自动写 `forbidden_word_hit_logs`（检测/审计路径）或 `manual_required=forbidden_word_hit`（LLM 生成后检查路径），可在运营后台观测命中分布，反向校验词库质量。
10. **作用范围差异（G1-DELTA 冻结）**：LLM 路径（禁止+重生成 1 次+仍命中转人工）覆盖抖音 AI 客服自动回复；微信派单/通知/反馈完全豁免抖音违禁词；抖音人工私信原文发送；抖音自动回访话术发送前检测命中阻断；回访模板命中 400 拒绝保存。
11. **PG downgrade 策略**：downgrade 0037→0036 **不删除词条**，只回退版本标记（无数据变更）；再次 upgrade 仍幂等。

## 6. 后续动作

- [x] **编写数据库迁移（已完成）**：SQLite `0047_forbidden_word_seed.sql` + PG Alembic `0037_forbidden_word_seed.py`，403 条，safe_word 全 NULL，幂等。
- [ ] 迁移后抽样测试检测效果（可复用 `tests/test_forbidden_word_service.py` / `tests/test_forbidden_word_policy.py` 模式）与 LLM 生成后检查命中转人工/重生成行为
- [ ] 观察 `forbidden_word_hit_logs` / `manual_required=forbidden_word_hit` 命中数据，迭代词库
- [ ] 单字/宽匹配词（改/V/最/666 等）上线后按命中日志评估是否收窄（V/最 已排除不入库；666 保留待观测）

---

## 附录 A：提取过程说明

- 工具：`pdftotext`（poppler）+ `pymupdf`（Python 3.14），规避模型直接读取 PDF 导致的 400 错误。
- PDF-B 部分字体（KaiTi/GBK-EUC-H CMap）提取有乱码，已通过 PyMuPDF 二次提取核对。
- 乱码词汇（约 25 项）按甲方决策 B 直接忽略，未列入词库。
- 全文词条提取自 PDF-A 3 页 + PDF-B 11 页，覆盖"违规词总结 / 通用敏感词 / 直播间违规情况整理 / 短视频违规事项"四个部分中与汽车直播强相关章节。
- **2026-08-19 复核补充**：首次核对后遗漏的 PDF 原文明列词条已补齐，包括：首/家/国类（首个、全球首发、全国首家、独家等）、独家/缔造类（独创、开发者、缔造者等）、极限补充（完美、淋漓尽致、一天、三甲、十强）、利益诱导/互动类（粉丝灯牌、礼物、上飞机、保时捷墨镜、拍了、666、报名、金钱、红包、低价引流）、歧视类（贵族、上流、富人区等）、线下引流补充（地址、qq、私信主播）、涉政补充（国歌、政府机关）、负面（赌博、抽烟、喝酒）、血腥/暴力、公众人物形象、限时补充（几天几夜、周年庆、品牌团）、回收。

## 附录 B：源文件索引

- `E:\work\project\project_info\Project_autowechat\直播违规注意事项.pdf`
- `E:\work\project\project_info\Project_autowechat\抖音汽车直播违禁词规避及辟谣指南.pdf`
- 提取文本暂存：`E:\tmp\wg01_m.txt` / `E:\tmp\wg02_m.txt`
