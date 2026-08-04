# P0-AI-EDIT-RESULT-DELIVERY 生产发布准备方案

> 提交基线：`b3cf1c8`（origin/master，已 push 未部署）
> 审批状态：APPROVED_FOR_COMMIT_NOT_FOR_PRODUCTION
> 风险域：数据库迁移 + 环境变量 + 部署（按 CLAUDE.md 必须先风险分析）

---

## 一、变更范围

### 1.1 代码提交
- HEAD：`b3cf1c8` 优化：AI剪辑标题改ASR优先+前端自动轮询+预估耗时调大
- 基线起点：`7ea01a8` 功能：AI剪辑结果交付闭环（后续叠加 8 个修复/优化提交）
- 已 push 到 origin/master（待部署，需 APPROVED_FOR_PRODUCTION）

### 1.2 数据库迁移
- **PG Alembic 0025**（`migrations/postgres/auto_wechat/versions/0025_ai_edit_result_delivery.py`）
  - `ai_edit_jobs` +9 列（title/title_source/title_generated_at/delivery_status/video_tags/deleted_at/deleted_by/delete_status/delete_error）
  - `ai_edit_job_artifacts` +5 列（is_final_video/delivery_status/archive_object_key/archive_error/file_size_bytes）
  - 历史回填：`delivery_status='pending'`、`title='混剪任务 #' || id`（title_source=fallback）
  - 所有新列可空，无破坏性变更，downgrade 完整
- **SQLite 0045**（`migrations/versions/0045_ai_edit_result_delivery.sql`）同步

### 1.3 环境变量（新增/确认）
本轮**不新增** env 变量，复用现有 TOS 配置：
- `TOS_ACCESS_KEY` / `TOS_SECRET_KEY` / `TOS_BUCKET` / `TOS_REGION` / `TOS_ENDPOINT`（已有，归档用）
- `LAS_API_KEY` / `LAS_BASE_URL`（已有，LAS 提交用）
- `LAS_TOS_PRESIGN_EXPIRES_SECONDS`（已有，播放下载签名有效期）

**需现场确认**：生产 `.env.production.local` 的 TOS 配置是否齐全且为自有 bucket `videoedit`（非 LAS bucket）。

---

## 二、执行步骤（待 APPROVED_FOR_PRODUCTION 后执行）

### 步骤 1：确认远端代码
```bash
# 代码已 push 到 origin/master（b3cf1c8），无需再 push
git log --oneline -1 origin/master   # 确认 = b3cf1c8
```

### 步骤 2：宝塔拉取代码
```bash
cd /www/wwwroot/XG_AI_System
git pull origin master
git log --oneline -1   # 确认 = b3cf1c8
```

### 步骤 3：执行 PG 迁移 0025
⚠️ 高风险域（数据库迁移），按 Runbook 操作：
```bash
cd /www/wwwroot/XG_AI_System
bash scripts/production_pg_alembic_upgrade.sh --service 9000 2>&1 | tee /tmp/step_alembic_0025.log
# 成功标准：[PASS] 9000 达 0025_ai_edit_result_delivery + ALEMBIC_UPGRADE_DONE
```
**回滚触发**：upgrade 失败或未达 0025 → 执行 `production_pg_rollback.sh`（PG volume 不删，数据保留）

### 步骤 4：确认 TOS 配置
```bash
grep -E "^(TOS_ACCESS_KEY|TOS_SECRET_KEY|TOS_BUCKET|TOS_REGION|TOS_ENDPOINT)=" .env.production.local
# 确认：TOS_BUCKET=videoedit，TOS_REGION 与 bucket 实际 region 一致
```

### 步骤 5：重启 9000
```bash
docker compose restart auto-wechat-api
# 就绪确认
curl -s http://127.0.0.1:9000/ready
docker compose logs --tail=50 auto-wechat-api | grep -iE "error|traceback"
```

### 步骤 6：smoke 验证
```bash
# 任务列表（应返回新字段 title/video_tags/has_final_video，不含 tos://）
curl -s -H "Authorization: Bearer $JWT" http://127.0.0.1:9000/api/ai-edit/las/jobs | python -m json.tool | head -30
```

### 步骤 7：历史任务修复（可选，逐任务确认）
```bash
# 标题补全（dry-run 先看）
python scripts/fix_ai_edit_jobs.py backfill-titles --limit 50
# 确认无误后 --execute
python scripts/fix_ai_edit_jobs.py backfill-titles --limit 50 --execute

# 视频归档（逐任务确认 LAS task 未 EXPIRED）
python scripts/fix_ai_edit_jobs.py archive-videos --job-id N   # dry-run
# 确认 LAS task 有效后
python scripts/fix_ai_edit_jobs.py archive-videos --job-id N --execute
```

---

## 三、风险分析

| 风险 | 等级 | 缓解 |
|---|---|---|
| 迁移 0025 失败 | 高 | 走 Runbook，可回滚（PG volume 不删） |
| TOS 配置错误导致归档失败 | 中 | 步骤4现场确认 bucket/region |
| 历史 LAS task 已 EXPIRED 无法归档 | 中 | archive-videos 记录失败不伪造，逐任务确认 |
| 前端构建产物未更新 | 低 | docker compose up --build 重建 frontend |
| 删除功能 TOS 失败 | 已缓解 | R2 修复：返回 500 不假装成功，可重试 |

---

## 四、回滚方案

```bash
# 代码回滚（revert 整个交付闭环 + 后续 LAS 修复，或回退到 7ea01a8 之前）
git revert b3cf1c8 --no-edit   # 或 git checkout 7ea01a8~1
docker compose restart auto-wechat-api

# 迁移回滚（如 0025 有问题）
bash scripts/production_pg_rollback.sh --execute --approver Waston --operator VHwwsf \
  --reason "0025 迁移问题" --backup-dir backups/cutover-<TS>
```

---

## 五、未解决事项

1. **LAS 远端删除 unsupported**：LAS bucket 产物不清理，仅删自有归档+禁用访问入口（符合设计）
2. **历史 LAS task EXPIRED**：archive-videos 对 EXPIRED task 记录失败不伪造，需逐任务确认
3. **下载 token fail-closed**：`_download_signing_secret` 已改为 DY_SECRET_KEY 缺失即拒签发/拒校验，生产部署前必须确认 `.env.production.local` 配置了 `DY_SECRET_KEY`（与 webhook 验签同源）

---

## 六、当前状态

- ✅ 代码 commit `b3cf1c8`（origin/master，已 push）
- ⏳ 生产发布待 APPROVED_FOR_PRODUCTION
- 本方案为准备文档，不含任何生产执行
