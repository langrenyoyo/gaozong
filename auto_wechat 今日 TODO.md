# auto_wechat 今日 TODO

> 更新时间：2026-08-06
> 维护方式：完成项标记 ✅，进行中标记 🔧，待办标记 ⬜

---

## 一、空号追问链路收尾（块1-4 已提交，遗留项）

| # | 事项 | 优先级 | 状态 |
|---|---|---|---|
| 1.1 | P0 止血（删 Task2A + 语义占位 `_mask_latest_message_for_llm` + 后置校验 `_check_valid_contact_conflict`）——审查通过，修复不完全，仍在测试/验证/修改 | 高 | 🔧 测试验证中 |
| 1.2 | `sent_message_id` 键名错误（`message_id`→`upstream_msg_id`） | 中 | ✅ 已完成 |
| 1.3 | 块3 Worker 发送集成测试/手动验证（send_source 白名单生效 + 真实发送链路） | 中 | ⬜ 待做 |
| 1.4 | 前端手动标记 API + UI（`POST /admin/contact-invalid/mark`，替代已删除的 Task2A，参考 task_id 强锚定） | 中 | ⬜ P1 闭环 |
| 1.5 | 三态拆分（收集/格式/可达）完整实现——P0 已用语义占位+后置校验止血，三态是完整方案 | 低 | ⬜ P1 闭环 |
| 1.6 | 微信反馈触发验证（Task2B reply_checker 路径，依赖销售微信回写） | 中 | ⬜ P1 闭环 |

---

## 二、线索识别规则增强（差距清单，文档已归档 `docs/ai/01_product_prd/线索识别AI技能规则.md`）

| # | 事项 | 优先级 | 缺口 |
|---|---|---|---|
| 2.1 | 清洗管道：全角转半角 + 剔除字母/中文 + 中文数字映射（`幺叁八`→138） | **高** | 缺口2，客户混淆手段核心 |
| 2.2 | 运营商号段白名单校验（防 11 位非号码数字串误判） | **高** | 缺口1 |
| 2.3 | 置信度字段（`ContactExtractResult` 加 confidence，与五态并存） | 中 | 缺口3 |
| 2.4 | LEAD_REQUEST 上下文增强（AI 留资提问后客户回复的数字加信） | 中-高 | 缺口4，核心机制 |
| 2.5 | 干扰词上下文降权（公里/万/元/年邻近数字降权） | 中 | 缺口6 |
| 2.6 | 手机号即微信识别（type=both） | 低 | 缺口5 |
| 2.7 | emoji 分隔符处理 | 低 | 缺口7 |
| 2.8 | 30 天去重窗口（可能在 lead 层，需确认） | 低 | 缺口8 |

---

## 三、生产遗留问题（P1/P2/P3 技术债）

| # | 事项 | 优先级 | 说明 |
|---|---|---|---|
| 3.1 | Webhook 缺签名放行——现场确认 Nginx `/webhook/` IP 白名单是否配置 | **P1 安全** | 代码设计合理（GMP 不带签名靠 Nginx IP 白名单），需现场验证 |
| 3.2 | `customer_profiles` JSONB/TEXT 不一致——统一 ORM/迁移为 JSONB + 补正式迁移 + 四种升级测试 | **P1 技术债** | 0026 迁移用 TEXT，生产是 JSONB，新环境会分裂 |
| 3.3 | `leads_internal_webhook_fallback` 持续连接失败——查 9202 配置/废弃则关闭/加熔断 | P1/P2 | 每条 webhook 失败一次再回退，主链路不受影响 |
| 3.4 | 前端字体 `Barlow-Regular_2.ttf` 404——补文件到 `public/fonts/` 或改引用路径 | P2 | `index.css:9` 引用，public 下无此文件 |
| 3.5 | 前端主包 ~1MB——路由懒加载 + vendor 分包 | P3 | 性能技术债 |
| 3.6 | 自动回复 run 重复 INSERT 是否与 `trigger_event_key` 同一问题——待澄清 | 待澄清 | models.py:554 unique=True |

---

## 四、之前审查发现的低优先级未修项

| # | 事项 | 来源 |
|---|---|---|
| 4.1 | `unfunded` 停用后死代码残留（`UNFOUNDED_FOLLOWUP_KEYWORDS`/`FOLLOWUP_PRECONDITION_KEYWORDS` 常量 + 别名导入 + validator 死调用） | 44cd66d 审查 |
| 4.2 | 测试名 `test_p0a_unfounded_followup_hard_blocked` 与断言放开不符 | 44cd66d 审查 |
| 4.3 | `history_text` 死代码（prompt_injection 修复后残留，`_conversation_history_text_for_risk` 调用） | prompt_injection 修复审查 |
| 4.4 | `test_customer_reset` requirements 重置清 inferred 不清 `confirmed_fields_json`（重置不彻底） | 测试客户重置审查 |
| 4.5 | `test_customer_reset` full 重置未清 `contact_extract_status/reason`（状态不一致） | 测试客户重置审查 |
| 4.6 | `_replace_sensitive_words` 无测试（涉及平台封禁风险） | 敏感词替换审查 |
| 4.7 | `_detect_contact_validity_from_outbound` 死代码（Task2A 删除后无调用者，已注释保留） | P0 止血审查 |
| 4.8 | 微信号脱敏星号 `wx***23` 未被语义占位正则覆盖（只覆盖手机号 `\d{3}\*+\d{0,4}`） | P0 止血审查 |

---

## 五、文档维护

| # | 事项 | 状态 |
|---|---|---|
| 5.1 | P0 止血（删 Task2A + 语义占位 + 后置校验）提交后补记 `05_PROJECT_CONTEXT.md` | ⬜ 待 1.1 完成后补记 |
| 5.2 | 线索识别规则增强（缺口 2.1-2.8）实施后补记 `05_PROJECT_CONTEXT.md` | ⬜ 待实施后补记 |

---

## 推进顺序

1. **立即**：1.1（P0 止血测试验证收尾）→ 1.3（块3 Worker 测试）
2. **高优先级**：2.1（清洗管道）+ 2.2（号段白名单）——线索识别反混淆核心，纯函数增强风险低
3. **P1 安全**：3.1（Nginx 白名单现场确认）+ 3.2（JSONB/TEXT 统一）
4. **中优先级**：1.4（前端手动标记 API）+ 2.4（LEAD_REQUEST 上下文）
5. **低优先级**：四类死代码清理（4.1-4.8）+ 前端字体/包体积（3.4/3.5）
