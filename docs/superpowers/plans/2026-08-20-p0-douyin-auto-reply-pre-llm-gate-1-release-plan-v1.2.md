# P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1 — RELEASE PLAN v1.2

> 状态：READY_FOR_APPROVAL（等待 Owner / Decision Authority 审批，审批前不执行）
> 角色：Implementation Planner（本计划只描述发布方案，不修改代码、不提交、不部署）
> 修订：v1.1（CHANGES_REQUIRED）→ v1.2 修正 Decision Authority 四项阻断（EXPECTED_REVISION / 部署命令 / seed 环境封闭 / 不一致窗口策略）

## 0. 审批状态基线

```
DECISION AUTHORITY   = Design accepted + Implementation accepted
VERIFICATION AUTHORITY = Local verification PASS + E2E verification PASS
REMAINING            = production seed / production deploy / G3 verification
RELEASE PLAN         = v1.2（本文件，READY_FOR_APPROVAL）
PRODUCTION DEPLOY    = NOT AUTHORIZED（v1.2 审批 APPROVED_FOR_COMMIT 后进入执行窗口）
```

## 1. Release Scope

```
部署目标：把 P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1（消息级禁止自动回复 + 商户后台可解释性）上线到生产（xg-prod）

包含：
  1. pre-LLM gate：evaluate_pre_llm_gates 新增 prohibited_auto_reply_input 消息级阻断
  2. 词库交付：prohibited_auto_reply（黑户/老赖/我黑了/征信花了）+ 幂等 seed 脚本
  3. additive API：auto_reply_status / auto_reply_reason（运行记录列表/详情）
  4. 前端 message-level 展示（"本条消息未自动回复"固定文案）
  5. G3 生产证据登记

真实发送口径：不主动触发真实客户发送；仅验证发送门禁链路未进入 send_msg（SEND=0 证据）。
明确不做（禁止扩大）：
  - 不改 schema / 不加 migration（DB_DELTA=SEED_ONLY）
  - 不改 webhook / outbox / 9100 / Prompt / RAG / 真实发送链
  - 不触发人工接管 / 不改 conversation 状态
  - 不重建索引 / 不重分配历史流水
```

## 2. Commit Boundary

```
运行代码与治理文档生命周期不同：未来 rollback/cherry-pick/热修复 feature 不得影响治理记录。拆分两个 commit。

Commit A（运行代码发布）feat: add prohibited auto reply pre llm gate
  backend  ：app/services/douyin_autoreply_gate_service.py
             app/services/forbidden_word_seed.py
             scripts/seed_forbidden_words_prohibited_auto_reply.py
             app/schemas.py
             app/services/ai_auto_reply_run_query_service.py
  frontend ：frontend/src/api/types.ts
             frontend/src/features/douyin-cs/riskFlagLabels.ts
             frontend/src/features/douyin-cs/pages/DouyinAutoReplyRunsPage.tsx
  tests    ：tests/test_ai_auto_reply_dry_run.py
             tests/test_ai_auto_reply_runs_api.py
             tests/test_forbidden_word_seed_migration.py
  runtime docs：docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml
             docs/modules/M01-douyin-ai-cs/CURRENT_FLOW.md

Commit B（治理文档）docs: record prohibited auto reply gate release decision
  docs/superpowers/plans/2026-08-20-p0-douyin-auto-reply-pre-llm-gate-1.md
  docs/architecture/remediation/P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1-DECISION-DELTA-v1.0.md
  docs/superpowers/plans/2026-08-20-p0-douyin-auto-reply-pre-llm-gate-1-release-plan-v1.2.md

BASE_SHA = 80f06e0；master 直接提交（项目 worktree 偏好：原地执行，不开分支）
禁止 = 与其它任务候选混合提交；push 前经 APPROVED_FOR_COMMIT 审批
```

### 2.1 Release Identity（EXPECTED_REVISION = 数据库迁移版本，非 Git SHA）

```
AUTO_WECHAT_API_EXPECTED_REVISION = 0037   （9000 库当前迁移版本；本任务 seed-only 不升版本，服务器已核实 = 0037）
XG_DOUYIN_AI_CS_EXPECTED_REVISION = 0005   （9100 库冻结迁移版本；本任务不改 9100，服务器已核实 = 0005）

COMMIT_SHA（Commit A 的 Git SHA）单独记录为发布记录字段，不得写入 EXPECTED_REVISION。
G0 三方一致校验：镜像迁移 head（0037） = release identity expected（0037） = 实际数据库 revision（0037）
缺失/不匹配 → release runner preflight FAIL（release_9000_s10b.py EXPECTED_REVISION_VARS，R1-1）
```

## 3. Files Included

```
Commit A（运行）：见 §2 Commit A 清单（backend 5 + frontend 3 + tests 3 + runtime docs 2 + seed script 1）
Commit B（治理）：见 §2 Commit B 清单（Delta v1.0 / Plan v1.0 / Release Plan v1.2）
```

## 4. Database Seed Plan（环境封闭）

```
目标库：xg-prod xg_ai_system-postgres-1 → auto_wechat（POSTGRES_USER=xgairoot）
当前事实：9000=0037 / 9100=0005；prohibited_auto_reply 词库 0 rows（未交付）
执行时点：seed 在 backend deploy 之前（方案二：seed → code，见 §5.1）

步骤（封闭环境，禁止宿主机默认环境执行）：
  S1. 脚本来源 = 已同步的固定 Commit A（production git sync 到 commit A SHA，仓库内该文件）
      禁止 scp 任意版本脚本；执行前校验脚本 SHA256 == Commit A 中同一文件 SHA256
  S2. 执行环境 = 目标 API 容器内（与生产同 env/依赖）：
      docker exec xg-auto-wechat-api python scripts/seed_forbidden_words_prohibited_auto_reply.py
      （或显式加载生产 runtime env 后执行；以运维确认的容器内路径为准）
      禁止在宿主机直接运行 SessionLocal()（避免连错库/连错环境）
  S3. 执行记录（Evidence）：COMMIT_SHA + 脚本 SHA256 + 目标数据库（host=…/db=auto_wechat）+ 执行时间
  S4. 只读核验 4 项 SQL（G3 / smoke 证据附件）：
      Q1: SELECT version_num FROM alembic_version;      → 0037（seed-only 不升版本，属预期）
      Q2: prohibited_auto_reply 词库 LEFT JOIN 词条     → 4 词条（黑户/老赖/我黑了/征信花了，severity=critical，enabled=true）
      Q3: 排除词 IN ('贷款','金融','分期','征信') 在新库  → 0 rows
      Q4: finance_compliance 原词条 IN (...)             → 保留（分期/征信/贷款/金融/黑户）

幂等保证：词库按 library_key 唯一、词条按 (library_id,word) 唯一；重复执行不重复插入；不覆盖已有词库配置/词条运营状态。
```

## 5. Deployment Sequence（seed → code，方案二）

```
前置审批：Owner / Decision Authority 批准 v1.2（APPROVED_FOR_COMMIT）→ 执行窗口授权
顺序：
  D1. Commit A（feature）+ Commit B（governance）   §2
  D2. regression                                   105+139 聚焦集；1 pre-existing 失败已知（§9.2）
  D3. push                                          APPROVED_FOR_COMMIT 后
  D4. production git sync                           xg-prod 同步到 Commit A（固定 revision）
  D5. production seed（先于代码切换）               §4 S1-S4（方案二：seed 先行，证明见 §5.1）
  D6. backend candidate build                       镜像构建 + release identity（EXPECTED_REVISION=0037/0005）
  D7. backend deploy                               统一入口：
      python scripts/prod_release.py deploy --service api --apply
      （内部复用 G0 runner release_9000_s10b.py；禁止直接向 runner 传 -p/--no-deps/--no-build/服务名——
        这些由 prod_release.py 内部生成；G0：禁止旁路部署框架）
  D8. frontend build/deploy                         前端 dist 重建并发布（message-level 展示）：
      python scripts/prod_release.py deploy --service frontend --apply
  D9. smoke                                         §6
  D10. G3 verification                              §8 生产证据
  D11. 完成报告 + 停
```

### 5.1 不一致窗口消除策略（方案二：seed → code + 旧代码无害性证明）

```
选择方案二（seed 先行），论证旧代码在 seed 先行时不会产生不允许的行为：

1. 词库是被动数据：prohibited_auto_reply 词库当前 0 rows；只有新 gate 代码（evaluate_pre_llm_gates 内
   _evaluate_prohibited_auto_reply）消费它做 pre-LLM 阻断。

2. 旧代码（HEAD 80f06e0）对新增全局词库的行为 = 既有普通违禁词语义：
   - check_forbidden_words：只检测/审计（写 ForbiddenWordHitLog + hit_count），不阻断、不替换、不发送、
     不改会话状态（违禁词方案冻结语义，2026-08 已实施）；
   - load_forbidden_words_for_llm：把新库 4 词注入 9100 Prompt 作为"LLM 输出约束词"——这与 finance_compliance
     等既有全局词库完全一致，属于既有普通违禁词行为，不产生"不允许的行为"（不阻断、不发送、无状态变化）。

3. 因此 seed 先行窗口 = "词库存在 + 旧代码只做普通违禁词处理"，行为等价于当前生产基线（黑户走既有链路）
   + 额外审计日志/词库命中统计，无危险行为、无错误发送、无错误阻断。

4. 新代码（gate 消费词库做 pre-LLM 阻断）在 seed 已就绪后上线 → gate 立即可命中，无"代码已上线但词库缺失"
   的漏过窗口。

5. 回滚安全：若 D7 后回滚代码到旧版本，旧代码继续把 4 词当普通违禁词处理（无害），seed 数据保留不删。

结论：seed → code 顺序消除"新代码上线但词库缺失 → 黑户漏过"的不一致窗口；seed 先行对旧代码无害。
```

## 6. Smoke Test Plan

```
S.1 服务健康：GET /ready（HTTP 200 / postgresql / alembic 0037）
S.2 数据库只读核验：§4 S4 的 4 项 SQL 全部满足
S.3 门禁行为（只读，不真实发送）：
    - 受控高风险输入经 webhook → 观测 AiAutoReplyRun：
      status=blocked / block_reason=prohibited_auto_reply_input / gate_results.pre_llm.prohibited_auto_reply.blocked=true
    - 普通消息回归：普通询价消息 run 走既有链路（不被新库误阻断）
S.4 additive API：GET /ai-auto-reply-runs 返回 auto_reply_status/auto_reply_reason
    （prohibited 命中项 = not_replied / prohibited_auto_reply）
S.5 前端：工作台运行记录列表/详情展示固定文案，刷新后仍在（message-level）
S.6 发送口径：不主动触发真实客户发送；仅验证发送门禁链路未进入 send_msg（SEND=0 证据）
```

## 7. Rollback Plan

```
代码回滚（首选）：
  R1. 回滚 9000/前端 镜像到前一发布版本：
      python scripts/prod_release.py rollback --service api --apply
      python scripts/prod_release.py rollback --service frontend --apply
  R2. 重新 smoke（/ready + 只读核验）

数据回滚（seed）：
  - 不删除词条（遵守"不删数据"原则）；回滚代码后旧代码把 4 词当普通违禁词处理（无害，§5.1）
  - 若需禁用：UPDATE forbidden_words SET enabled=false WHERE library_id=<新库 id>（仅经审批，幂等可逆）

回滚触发条件：/ready 失败 / smoke S.3 行为异常 / additive API 字段缺失 / 前端白屏
```

## 8. G3 Verification Matrix（生产证据）

```
G3_DELTA = YES（本任务）

M01-PRE-LLM-BLOCK-1（生产证据）：
  输入：受控高风险消息"我是黑户"进入自动回复链
  数据库证据：AiAutoReplyRun
      status = blocked
      block_reason = prohibited_auto_reply_input
      gate_results.pre_llm.prohibited_auto_reply.blocked = true
  日志证据（生产观测）：
      9100 call = 0（无 suggest_reply 调用）
      send_msg call = 0（发送门禁链路未进入 send_msg）
  词库证据：§4 Q2（prohibited_auto_reply 4 词条存在）

M01-PRE-LLM-RECOVERY-1（生产证据）：
  输入：连续两条 —— "我是黑户" → "多少钱"
  数据库证据：
      第一条 AiAutoReplyRun.status = blocked（block_reason=prohibited_auto_reply_input）
      第二条 AiAutoReplyRun 进入正常 AI 链路（status=decided，正常调用 9100）
  证明：message-level only（前一条命中不污染后一条）
  日志证据：第二条 9100 call = 1；第一条 send_msg call = 0

TENANT_ISOLATION：
  词库 scope=global（全局规则，符合现有全局违禁词语义）
  API forged merchant_id 不绕过（本地 runs_api 覆盖 + 生产沿用可信 context 过滤）

G3 SSOT：docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml 已登记，生产证据回填运行 HEAD
```

## 9. 风险与已知项

```
9.1 服务器 alembic：9000=0037 / 9100=0005（已核实）；seed-only 不升版本，Q1 断言 0037
9.2 test_p0a_hard_gate pre-existing 失败（HARD_BLOCK_RISK_FLAGS 与测试漂移，2026-08-04 既有）——不在本发布范围
9.3 前端 dist 需重新构建（当前 dist 不含 message-level 展示）
9.4 生产部署必须经 prod_release.py 统一入口（内部复用 G0 runner），禁止直接调 release_9000_s10b.py 传 Compose 参数
9.5 生产 G3 证据需受控测试账号（仅观测决策日志，不触发真实客户发送）
9.6 seed 脚本必须来自固定 Commit A 并在容器内执行（§4 S1-S2），记录 SHA256/目标库
```

## 10. 结论

```
RESULT = READY_FOR_APPROVAL（v1.2 已修正 Decision Authority 全部 4 项阻断）
RELEASE PLAN = v1.2
PRODUCTION_DEPLOY = NOT_EXECUTED（等待 APPROVED_FOR_COMMIT 后进入执行窗口）
COMMIT = NO / PUSH = NO / DEPLOYMENT = NO
STOP
```
