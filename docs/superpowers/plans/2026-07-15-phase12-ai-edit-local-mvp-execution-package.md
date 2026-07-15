# Phase 12 AI剪辑本地 MVP 实施计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `auto_wechat` 中迁入“小高素材库 + AI 小高剪辑”本地 MVP，让商户在安装小高AI微信助手的同一台 Windows 电脑完成素材导入、分析、可选增稳、模拟 AI 规划、轻量调整、720P 预览和 1080P 成片。

**Architecture:** 9000 负责权限、商户 metadata、任务和审计；9100 只处理结构化剪辑规划；19000 管理本地素材、单任务队列和子进程；随安装包交付的 Python 3.11 `ai_edit_worker.exe` 执行 ASR、分析、增稳和渲染。媒体默认留在本机，用户主动选择后才上传云端。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite 顺序迁移、PostgreSQL Alembic、React + TypeScript + Vite、PyInstaller、Python 3.11 Worker、FFmpeg/ffprobe、Vid.Stab、FunASR、PySceneDetect、OpenCV、YOLO、open_clip。

**计划状态：** `FROZEN`。Phase 12 实现仍为 `NOT_STARTED`，执行时按 Task 0-10 和检查点 A/B/C 推进。

---

## 0. 总控边界

### 0.1 权威输入

- 冻结设计：`docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`
- auto_edit 审计：`docs/ai/13_ai_edit/auto_edit_Phase12_AI剪辑迁入准备审计报告.md`
- BrollStudio 审计：`docs/ai/13_ai_edit/BrollStudio_空镜素材复用与视频增稳评估报告.md`
- auto_edit 来源基线：`E:\work\project\auto_edit`，`develop@d0c81895f770`
- BrollStudio 来源：`E:\work\project\BrollStudio_空镜素材增稳分析入库工具_交付包_20260714_114227`

来源仓库只读。只迁入经审计选定的源码，不复制 `runs/`、数据库、密钥、模型缓存、PySide6、开发 runner 或外部绝对路径。

### 0.2 生产与网络红线

- 不连接宝塔、生产数据库、真实抖音或真实付费模型。
- 自动测试中的 9000/9100、LLM、Embedding 和外部 HTTP 全部使用替身。
- 允许在本地用合成媒体执行 FFmpeg/Vid.Stab；最终本地验收允许使用已授权汽车素材，但 9100 仍使用替身。
- 宝塔与真实模型验证统一留到 Phase 13 完成后的生产验证执行包。

### 0.3 工作区保护

每个 Task 开始和提交前执行：

```powershell
git status --short
git diff --check
```

只 `git add` 当前 Task 白名单文件。不得提交现有 `.gitignore`、一期 PRD、`docs/待确认事项.md`、Phase 8 测试、生成的 `.d.ts` 或其他并发窗口文件。

### 0.4 加速节奏与硬检查点

- Task 0-2 连续执行，Task 2 后进入**检查点 A：数据与安全合同**。
- 检查点 A 通过后连续执行 Task 3-8，Task 8 后进入**检查点 B：19000/Worker 安全边界**。
- 检查点 B 通过后连续执行 Task 9-10，Task 10 后进入**检查点 C：阶段总验收**。
- 除三个硬检查点外，各 Task 提交后直接进入下一 Task；出现 Must-Fix 时单开 `Task N-FIX`。

每个 Task 固定回传：提交哈希、精确文件、红灯、绿灯、关联回归、真实网络调用数、真实媒体调用范围、脏工作区保护和残留风险。

## 1. 文件结构

### 9000 控制面

```text
app/models.py                         AI剪辑 ORM
app/schemas.py                        外部与 Local Agent DTO
app/routers/ai_edit.py                商户、超管和 Local Agent API
app/services/ai_edit_service.py       商户隔离、状态机、任务与素材业务
app/services/ai_edit_storage.py       缩略图和主动云端产物受控存储
app/services/xg_douyin_ai_cs_client.py 9000 -> 9100 剪辑规划窄方法
```

### 9100 规划

```text
apps/xg_douyin_ai_cs/routers/ai_edit.py
apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py
apps/xg_douyin_ai_cs/schemas.py
```

### 本地 Worker 与 19000

```text
apps/ai_edit/contracts.py             Worker 严格任务合同
apps/ai_edit/core/                    精选迁入的纯逻辑
apps/ai_edit/media_tools.py           可取消 FFmpeg/ffprobe 执行器
apps/ai_edit/stabilizer.py            Vid.Stab 自动增稳
apps/ai_edit/pipeline.py              ASR、规划输入、字幕、BGM、渲染编排
apps/ai_edit/worker_main.py            Python 3.11 Worker 入口
app/local_agent_ai_edit_storage.py    本地受管素材和回收站
app/local_agent_ai_edit_supervisor.py 队列、子进程、取消和恢复
app/local_agent_ai_edit_routes.py     19000 AI剪辑路由
```

### 前端

```text
frontend/src/features/ai-edit/types.ts
frontend/src/features/ai-edit/api.ts
frontend/src/features/ai-edit/localApi.ts
frontend/src/features/ai-edit/routes.ts
frontend/src/pages/MaterialLibrary.tsx
frontend/src/pages/AiVideoEditor.tsx
```

---

## Task 0：基线、权属与工具预检

**Files:** 无修改

- [ ] **Step 1: 核对三仓库基线和脏工作区**

```powershell
git status --short --branch
git -C E:\work\project\auto_edit rev-parse --short=12 HEAD
Test-Path E:\work\project\BrollStudio_空镜素材增稳分析入库工具_交付包_20260714_114227\source\broll_asset_analyzer\stabilizer.py
```

Expected：目标仓库脏文件已记录但不修改；auto_edit 输出 `d0c81895f770`；BrollStudio 文件存在。

- [ ] **Step 2: 核对本机工具边界**

```powershell
C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe --version
python --version
ffmpeg -hide_banner -version
ffmpeg -hide_banner -filters | Select-String "vidstabdetect|vidstabtransform"
```

Expected：现有 Local Agent 为 Python 3.10；Worker 构建解释器必须另用 Python 3.11；FFmpeg 能力缺失只记录为 Task 8 打包输入，不修改全局 PATH。

- [ ] **Step 3: 固定迁入白名单**

允许从 auto_edit 迁入：`models.py`、`edit_grammar.py`、`edit_quality_filter.py`、`llm_output_validation.py`、`subtitle_text_cleaner.py` 中的通用逻辑，以及 ASR/渲染必要实现。

允许从 BrollStudio 迁入：`stabilizer.py`、`video.py` 中 SHA-256、ffprobe、代理和 Vid.Stab 必要实现。

禁止迁入：`dealer_task_store.py`、`scripts/dev/`、`runs/`、PySide6、SQLite、固定豆包客户端和来源项目环境文件。

Task 0 不提交。

---

## Task 1：冻结数据合同红灯

**Files:**
- Create: `tests/test_phase12_ai_edit_schema.py`
- Create: `tests/test_phase12_ai_edit_postgres_contract.py`

- [ ] **Step 1: 写 ORM 红灯**

测试固定四个新对象和现有两表扩展：

```python
EXPECTED_TABLES = {
    "ai_edit_materials",
    "ai_edit_material_analyses",
    "ai_edit_templates",
    "ai_edit_job_materials",
}

def test_phase12_tables_and_existing_shell_extensions():
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    assert {
        "stage", "progress", "agent_client_id", "attempt_count",
        "execution_token_hash", "cancel_requested_at", "heartbeat_at",
        "input_fingerprint", "engine_version", "template_version",
        "model_version", "failure_code", "error_summary",
    } <= set(AiEditJob.__table__.columns.keys())
```

另断言：

- `material_id/template_key/job_id+material_id+role+position` 唯一约束。
- `scope in ('merchant','platform')`、`storage_mode in ('local_only','uploading','cloud_available','local_missing')`。
- `progress between 0 and 100`、`attempt_count >= 0`。
- 9000 表不出现 `absolute_path/source_path/local_path` 列。
- artifact 增加位置类型、设备、SHA-256、媒体属性和完整性状态。

- [ ] **Step 2: 写 SQLite 行为红灯**

使用 `tmp_path` 基线库验证：

```python
def test_sqlite_0032_upgrade_preserves_existing_ai_edit_rows(tmp_path):
    db = apply_through_0031(tmp_path)
    seed_ai_edit_shell_rows(db)
    apply_0032(db)
    assert existing_job_and_artifact_rows(db) == 2
    assert phase12_tables_exist(db)
```

同时覆盖未知列漂移拒绝、升级事务回滚、降级恢复 0031 列集、降级后可再次升级和越序降级拒绝。

- [ ] **Step 3: 写 PostgreSQL 静态合同红灯**

固定：

```python
def test_pg_0013_revision_and_no_create_all():
    text = PG_0013.read_text(encoding="utf-8")
    assert 'revision = "0013_ai_edit_local_mvp"' in text
    assert 'down_revision = "0012_compute_billing"' in text
    assert "create_all" not in text
```

断言只新建四表、ALTER 两表、索引/约束齐全，downgrade 只回退 0013 自身内容。

- [ ] **Step 4: 运行红灯**

```powershell
python -m pytest tests/test_phase12_ai_edit_schema.py tests/test_phase12_ai_edit_postgres_contract.py -q
```

Expected：只因 ORM 字段和 `0032/0013` 文件不存在而失败；不得有导入或 fixture 错误。

- [ ] **Step 5: 提交红灯**

```powershell
git add tests/test_phase12_ai_edit_schema.py tests/test_phase12_ai_edit_postgres_contract.py
git commit -m "测试：冻结 Phase 12 AI剪辑数据合同"
```

---

## Task 2：数据模型与双轨迁移

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Create: `migrations/versions/0032_ai_edit_local_mvp.sql`
- Create: `migrations/downgrades/0032_ai_edit_local_mvp.sql`
- Create: `migrations/postgres/auto_wechat/versions/0013_ai_edit_local_mvp.py`
- Test: `tests/test_phase12_ai_edit_schema.py`
- Test: `tests/test_phase12_ai_edit_postgres_contract.py`

- [ ] **Step 1: 实现最小 ORM**

模型合同：

```python
class AiEditMaterial(Base):
    __tablename__ = "ai_edit_materials"
    material_id = Column(String(64), nullable=False, unique=True)
    merchant_id = Column(String(128))
    scope = Column(String(16), nullable=False)
    media_type = Column(String(16), nullable=False)
    storage_mode = Column(String(32), nullable=False)
    agent_client_id = Column(String(128))
    source_sha256 = Column(String(64), nullable=False)
    parent_material_id = Column(String(64))
    thumbnail_storage_key = Column(String(255))
    cloud_storage_key = Column(String(255))
    analysis_status = Column(String(32), nullable=False)
    stabilization_status = Column(String(32), nullable=False)
    deleted_at = Column(DateTime)
    purge_after = Column(DateTime)

class AiEditMaterialAnalysis(Base):
    __tablename__ = "ai_edit_material_analyses"
    material_id = Column(String(64), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    analysis_version = Column(String(64), nullable=False)
    transcript_json = Column(Text, nullable=False)
    scenes_json = Column(Text, nullable=False)
    tags_json = Column(Text, nullable=False)
    usable_ranges_json = Column(Text, nullable=False)

class AiEditTemplate(Base):
    __tablename__ = "ai_edit_templates"
    template_key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    rules_json = Column(Text, nullable=False)
    prompt_version = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=false())

class AiEditJobMaterial(Base):
    __tablename__ = "ai_edit_job_materials"
    job_id = Column(String(64), nullable=False)
    material_id = Column(String(64), nullable=False)
    role = Column(String(16), nullable=False)
    position = Column(Integer, nullable=False)
    pinned_sha256 = Column(String(64), nullable=False)
    source_start = Column(Float)
    source_end = Column(Float)
```

JSON 文本必须经 Pydantic 严格 schema 序列化；禁止存模型自由原文。

- [ ] **Step 2: 实现 SQLite 0032**

使用项目现有安全重建模式：

```sql
BEGIN;
-- 前置校验 0031 为当前 head，ai_edit_jobs/artifacts 精确列集匹配。
-- 新建四表；安全重建 ai_edit_jobs 和 ai_edit_job_artifacts。
-- 行数、max(id) 和双向 EXCEPT 多重集守卫通过后登记 0032。
COMMIT;
```

不兜底创建 0027 已有表，不修改共享开发库。

- [ ] **Step 3: 实现 SQLite downgrade 与 PG 0013**

SQLite downgrade 恢复 0031 精确列集并保留历史行；PG 使用 `op.create_table` 和 `op.add_column`，默认值三方一致，禁止 `create_all`。

- [ ] **Step 4: 运行绿灯和迁移回归**

```powershell
python -m pytest tests/test_phase12_ai_edit_schema.py tests/test_phase12_ai_edit_postgres_contract.py tests/test_xiaogao_phase1_schema.py tests/test_db_migration_runner.py -q
python -m py_compile app/models.py app/schemas.py migrations/postgres/auto_wechat/versions/0013_ai_edit_local_mvp.py
git diff --check
```

Expected：Phase 12 合同全绿；历史 0027/0031 和 runner 回归零新增失败。

- [ ] **Step 5: 提交**

```powershell
git add app/models.py app/schemas.py migrations/versions/0032_ai_edit_local_mvp.sql migrations/downgrades/0032_ai_edit_local_mvp.sql migrations/postgres/auto_wechat/versions/0013_ai_edit_local_mvp.py tests/test_phase12_ai_edit_schema.py tests/test_phase12_ai_edit_postgres_contract.py
git commit -m "功能：增加 Phase 12 AI剪辑数据迁移"
```

### 检查点 A：数据与安全合同

必须由 Spec Reviewer、数据库 Reviewer、Security Reviewer 三方 PASS：

- 历史任务/产物无损，SQLite 升降级事务完整，PG revision 正确。
- 本地绝对路径不进入 9000 schema；商户与平台作用域可校验。
- 任务 attempt、执行令牌、取消、进度和媒体完整性字段足够支撑后续 Worker。

三方 PASS 前不得进入 Task 3。

---

## Task 3：9000 素材、模板与任务控制面

**Files:**
- Create: `app/services/ai_edit_storage.py`
- Create: `app/services/ai_edit_service.py`
- Create: `app/routers/ai_edit.py`
- Modify: `app/main.py`
- Modify: `app/schemas.py`
- Create: `tests/test_phase12_ai_edit_api.py`
- Create: `tests/test_phase12_ai_edit_service.py`

- [ ] **Step 1: 写权限、隔离和状态红灯**

覆盖：无权限 403、跨商户 404、平台素材只读、Local Agent token 商户映射、活动引用禁止删除、7 天回收站、取消/重试状态和 API 不返回路径/storage_key。

```python
def test_material_response_never_exposes_internal_paths(client):
    body = create_and_get_local_material(client)
    assert "storage_key" not in body
    assert "local_path" not in body
    assert "merchant_id" not in body
```

Run: `python -m pytest tests/test_phase12_ai_edit_api.py tests/test_phase12_ai_edit_service.py -q`

Expected：只因控制面模块、路由或 schema 尚不存在而失败，不得出现测试收集错误。

- [ ] **Step 2: 实现受控存储**

`ai_edit_storage.py` 只处理缩略图、平台公共素材和用户主动上传的云端产物：

```python
def resolve_ai_edit_storage_key(storage_key: str, root: Path) -> Path:
    target = (root / storage_key).resolve()
    target.relative_to(root.resolve())
    if target.is_symlink():
        raise AiEditStorageError("AI_EDIT_STORAGE_LINK_REJECTED")
    return target
```

复用日报存储的路径穿越、哈希和大小复验语义，不复制 `.xlsx` 限制。

- [ ] **Step 3: 实现业务服务和路由**

商户接口使用：

```python
_ai_edit_context = Depends(require_permission("auto_wechat:ai_edit"))
```

Local Agent 回写接口使用 `require_local_agent_context`。创建任务时在 `AiEditJobMaterial` 钉住素材哈希和区间；状态更新必须带 `job_id + execution_token_hash + attempt_count` 条件。

- [ ] **Step 4: 运行测试**

```powershell
python -m pytest tests/test_phase12_ai_edit_api.py tests/test_phase12_ai_edit_service.py tests/test_local_agent_auth.py -q
python -m py_compile app/services/ai_edit_storage.py app/services/ai_edit_service.py app/routers/ai_edit.py app/main.py
```

- [ ] **Step 5: 提交**

```powershell
git add app/services/ai_edit_storage.py app/services/ai_edit_service.py app/routers/ai_edit.py app/main.py app/schemas.py tests/test_phase12_ai_edit_api.py tests/test_phase12_ai_edit_service.py
git commit -m "功能：增加 AI剪辑素材与任务控制面"
```

---

## Task 4：9100 严格剪辑规划协议

**Files:**
- Create: `apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py`
- Create: `apps/xg_douyin_ai_cs/routers/ai_edit.py`
- Modify: `apps/xg_douyin_ai_cs/schemas.py`
- Modify: `apps/xg_douyin_ai_cs/main.py`
- Modify: `app/services/xg_douyin_ai_cs_client.py`
- Create: `tests/test_phase12_ai_edit_planner.py`
- Create: `tests/test_phase12_ai_edit_internal_api.py`

- [ ] **Step 1: 写严格协议红灯**

请求只允许：

```python
class AiEditPlanRequest(BaseModel):
    model_config = {"extra": "forbid"}
    merchant_id: str
    job_id: str
    template_key: str
    template_version: str
    target_duration_seconds: int = Field(ge=15, le=60)
    transcript_segments: list[TranscriptSegment]
    scenes: list[SceneSummary]
```

输出只允许 `keep/remove/broll_replace`；每段必须引用真实素材 ID 和合法区间。测试注入、拒答、空输出、越界、未知素材、重叠区间和模型异常。

Run: `python -m pytest tests/test_phase12_ai_edit_planner.py tests/test_phase12_ai_edit_internal_api.py -q`

Expected：只因规划服务和内部路由尚不存在而失败；LLM 和 HTTP 均不得真实调用。

- [ ] **Step 2: 实现一次 LLM 调用和保守校验**

```python
def plan_ai_edit(request: AiEditPlanRequest, llm_client) -> AiEditPlan:
    raw = llm_client.chat(_build_messages(request))
    plan = _parse_strict_plan(raw)
    return _validate_conservative_plan(plan, request)
```

不允许改写车辆事实；主口播默认保持时间顺序；失败明确返回稳定错误，不走自由文本或规则兜底。

- [ ] **Step 3: 接入内部鉴权与算力**

- 路由固定 `POST /internal/ai-edit/plan`，复用 `require_internal_service_token`。
- 9000 客户端新增 `plan_ai_edit(request)` 窄方法。
- 成功 LLM 调用按字符上报 `capability_key="compute"`；原媒体、图片和模型原始响应不进 payload/日志。

- [ ] **Step 4: 运行测试**

```powershell
python -m pytest tests/test_phase12_ai_edit_planner.py tests/test_phase12_ai_edit_internal_api.py tests/test_compute_usage_client.py -q
python -m py_compile apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py apps/xg_douyin_ai_cs/routers/ai_edit.py apps/xg_douyin_ai_cs/schemas.py app/services/xg_douyin_ai_cs_client.py
```

- [ ] **Step 5: 提交**

```powershell
git add apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py apps/xg_douyin_ai_cs/routers/ai_edit.py apps/xg_douyin_ai_cs/schemas.py apps/xg_douyin_ai_cs/main.py app/services/xg_douyin_ai_cs_client.py tests/test_phase12_ai_edit_planner.py tests/test_phase12_ai_edit_internal_api.py
git commit -m "功能：增加 9100 AI剪辑严格规划协议"
```

---

## Task 5：Worker 合同与纯逻辑内核

**Files:**
- Create: `apps/ai_edit/__init__.py`
- Create: `apps/ai_edit/contracts.py`
- Create: `apps/ai_edit/worker_main.py`
- Create: `apps/ai_edit/core/__init__.py`
- Create: `apps/ai_edit/core/models.py`
- Create: `apps/ai_edit/core/edit_grammar.py`
- Create: `apps/ai_edit/core/edit_quality_filter.py`
- Create: `apps/ai_edit/core/llm_output_validation.py`
- Create: `apps/ai_edit/core/subtitle_text_cleaner.py`
- Create: `tests/test_phase12_ai_edit_worker_contract.py`
- Create: `tests/test_phase12_ai_edit_core.py`

- [ ] **Step 1: 写 Worker 合同红灯**

```python
class WorkerManifest(BaseModel):
    model_config = {"extra": "forbid"}
    schema_version: Literal["phase12_ai_edit_worker_v1"]
    job_id: str
    attempt_id: str
    task_root: Path
    target_duration_seconds: int
    preview_profile: Literal["720p"]
    final_profile: Literal["1080p"]
    materials: list[WorkerMaterial]

class WorkerResult(BaseModel):
    status: Literal["review_required", "succeeded", "failed", "cancelled"]
    failure_stage: str | None
    artifacts: list[WorkerArtifact]
```

`task_root` 是 19000 生成并传给 Worker 的受信绝对任务目录；素材和产物在清单中只允许使用相对 `task_root` 的路径。测试拒绝额外字段、素材/产物相对路径逃逸、未知状态、无主素材和前端自报商户字段。

Run: `python -m pytest tests/test_phase12_ai_edit_worker_contract.py tests/test_phase12_ai_edit_core.py -q`

Expected：只因 Worker 合同和纯逻辑模块尚不存在而失败。

- [ ] **Step 2: 迁入最小纯逻辑**

从冻结来源基线逐文件迁入通用实现，保留来源注记并改包路径。删除样片品牌、商户、外部仓库路径和 raw response 写盘逻辑。只迁本 Task 白名单，不复制整个目录。

- [ ] **Step 3: 实现 Worker 最小入口**

```python
def main(argv: Sequence[str] | None = None) -> int:
    manifest = load_manifest(parse_manifest_path(argv))
    result = run_preflight_only(manifest)
    write_result_atomically(manifest.task_root / "result.json", result)
    return 0 if result.status != "failed" else 1
```

Task 5 只完成合同和预检，不提前实现媒体链。

- [ ] **Step 4: 运行测试并提交**

```powershell
python -m pytest tests/test_phase12_ai_edit_worker_contract.py tests/test_phase12_ai_edit_core.py -q
python -m py_compile apps/ai_edit/contracts.py apps/ai_edit/worker_main.py apps/ai_edit/core/*.py
git add apps/ai_edit tests/test_phase12_ai_edit_worker_contract.py tests/test_phase12_ai_edit_core.py
git commit -m "功能：迁入 AI剪辑 Worker 合同与纯逻辑内核"
```

---

## Task 6：可取消媒体链、自动增稳与双分辨率渲染

**Files:**
- Create: `apps/ai_edit/media_tools.py`
- Create: `apps/ai_edit/stabilizer.py`
- Create: `apps/ai_edit/pipeline.py`
- Modify: `apps/ai_edit/worker_main.py`
- Create: `tests/test_phase12_ai_edit_media_tools.py`
- Create: `tests/test_phase12_ai_edit_stabilizer.py`
- Create: `tests/test_phase12_ai_edit_pipeline.py`

- [ ] **Step 1: 写媒体红灯**

覆盖：命令超时、取消终止进程树、输出目录逃逸、源哈希不一致、Vid.Stab 保留音频、非 0 秒空镜区间、720P/1080P、字幕时间、BGM 压低和媒体强门。

```python
def test_stabilization_preserves_audio_and_source_hash(tmp_path):
    source = make_synthetic_av_video(tmp_path)
    result = stabilize(source, expected_sha256=file_sha256(source))
    assert probe(result.output).has_audio is True
    assert file_sha256(source) == result.source_sha256
```

Run: `python -m pytest tests/test_phase12_ai_edit_media_tools.py tests/test_phase12_ai_edit_stabilizer.py tests/test_phase12_ai_edit_pipeline.py -q`

Expected：只因媒体执行器、增稳器和流水线尚不存在而失败；合成素材以外的真实媒体读取为 0。

- [ ] **Step 2: 实现统一子进程执行器**

使用 `subprocess.Popen`，持续读取 stdout/stderr，支持阶段超时和取消文件；不继续使用不可取消的裸 `subprocess.run()`。

```python
def run_media_command(command, *, timeout_seconds, cancel_check, cwd):
    process = subprocess.Popen(command, cwd=cwd, stdout=PIPE, stderr=PIPE, text=True)
    try:
        return wait_with_cancel(process, timeout_seconds, cancel_check)
    finally:
        if process.poll() is None:
            terminate_process_tree(process)
```

- [ ] **Step 3: 迁入并修正 Vid.Stab**

- Worker 自行计算源哈希，不信任 manifest 外部哈希。
- 每 attempt 独立 `motion.trf` 和临时目录。
- 第二遍显式映射 `0:v:0` 与 `0:a?`，视频 `libx264`、音频 `aac`，禁止 `-an`。
- 缓存身份包含源哈希、参数摘要、算法版本和 FFmpeg 版本。

- [ ] **Step 4: 实现最小媒体流水线**

```text
preflight -> analyze -> stabilize_optional -> plan_input
-> render_preview_720p -> review_required
-> render_final_1080p -> verify -> succeeded
```

日常测试中的 ASR、YOLO、open_clip 和规划均注入替身；真实 FFmpeg 只处理合成媒体。

- [ ] **Step 5: 运行测试并提交**

```powershell
python -m pytest tests/test_phase12_ai_edit_media_tools.py tests/test_phase12_ai_edit_stabilizer.py tests/test_phase12_ai_edit_pipeline.py -q
python -m py_compile apps/ai_edit/media_tools.py apps/ai_edit/stabilizer.py apps/ai_edit/pipeline.py apps/ai_edit/worker_main.py
git add apps/ai_edit tests/test_phase12_ai_edit_media_tools.py tests/test_phase12_ai_edit_stabilizer.py tests/test_phase12_ai_edit_pipeline.py
git commit -m "功能：增加 AI剪辑可取消媒体流水线"
```

---

## Task 7：19000 本地素材、队列与恢复

**Files:**
- Create: `app/local_agent_ai_edit_storage.py`
- Create: `app/local_agent_ai_edit_supervisor.py`
- Create: `app/local_agent_ai_edit_routes.py`
- Modify: `app/local_agent_main.py`
- Create: `tests/test_phase12_local_ai_edit_storage.py`
- Create: `tests/test_phase12_local_ai_edit_supervisor.py`
- Create: `tests/test_phase12_local_ai_edit_routes.py`

- [ ] **Step 1: 写本地安全红灯**

覆盖：受管目录复制、原文件不变、路径穿越/符号链接拒绝、流式导入、磁盘预检、7 天回收站、活动任务禁止删除、单任务队列、取消、重启恢复和 Worker 缺失不影响微信路由。

Run: `python -m pytest tests/test_phase12_local_ai_edit_storage.py tests/test_phase12_local_ai_edit_supervisor.py tests/test_phase12_local_ai_edit_routes.py -q`

Expected：只因本地存储、监管器和路由尚不存在而失败；不得启动真实 Worker。

- [ ] **Step 2: 实现本地受管存储**

```python
def import_material(source_stream, *, material_id, expected_size, root):
    destination = resolve_managed_material_path(root, material_id)
    write_stream_to_temp_and_replace(source_stream, destination, expected_size)
    return probe_and_hash(destination)
```

本地清单只保存受管相对路径；写清单使用临时文件 + `os.replace`。一期单进程单写者，不新增本地数据库。

- [ ] **Step 3: 实现监管器**

```python
class AiEditSupervisor:
    def enqueue(self, job: LocalAiEditJob) -> None: ...
    def cancel(self, job_id: str) -> bool: ...
    def recover(self) -> int: ...
    def status(self) -> LocalAiEditStatus: ...
```

后台线程只负责队列和进程监管；媒体处理不在 19000 进程执行。默认并发 `1`，配置允许大于 `1`。

- [ ] **Step 4: 注册窄路由**

`create_local_agent_app()` 只增加：

```python
app.include_router(create_ai_edit_router(supervisor=supervisor, storage=storage))
```

不得把实现继续堆入 `local_agent_main.py`。路由复用既有 Local Agent token，不接受 `merchant_id` 和绝对路径。

- [ ] **Step 5: 运行回归并提交**

```powershell
python -m pytest tests/test_phase12_local_ai_edit_storage.py tests/test_phase12_local_ai_edit_supervisor.py tests/test_phase12_local_ai_edit_routes.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py tests/test_phase8b_poll_and_send_attachment.py -q
python -m py_compile app/local_agent_ai_edit_storage.py app/local_agent_ai_edit_supervisor.py app/local_agent_ai_edit_routes.py app/local_agent_main.py
git add app/local_agent_ai_edit_storage.py app/local_agent_ai_edit_supervisor.py app/local_agent_ai_edit_routes.py app/local_agent_main.py tests/test_phase12_local_ai_edit_storage.py tests/test_phase12_local_ai_edit_supervisor.py tests/test_phase12_local_ai_edit_routes.py
git commit -m "功能：接入本机 AI剪辑队列与进程监管"
```

---

## Task 8：双运行时打包与许可证门禁

**Files:**
- Create: `ai_edit_worker.spec`
- Create: `requirements-ai-edit-worker.txt`
- Create: `scripts/build_ai_edit_worker_exe.ps1`
- Modify: `scripts/build_local_agent_exe.ps1`
- Create: `docs/ai/13_ai_edit/THIRD_PARTY_NOTICES.md`
- Create: `tests/test_phase12_ai_edit_packaging_contract.py`

- [ ] **Step 1: 写打包合同红灯**

断言：

- Worker 构建脚本显式校验 Python 3.11，不改现有 Local Agent Python 3.10 spec。
- 安装目录同时包含两个 exe、FFmpeg/ffprobe、字体、模型目录和许可证文本。
- build script 缺 Worker、Vid.Stab、字体或模型时明确失败。
- Worker 不监听新端口，不把 19000 改成 `0.0.0.0`。

Run: `python -m pytest tests/test_phase12_ai_edit_packaging_contract.py -q`

Expected：只因 Worker spec、依赖清单、构建脚本或许可证文件尚不存在而失败。

- [ ] **Step 2: 实现独立 Worker 打包**

```powershell
param(
    [Parameter(Mandatory=$true)][string]$Python311Exe,
    [Parameter(Mandatory=$true)][string]$FfmpegDir,
    [Parameter(Mandatory=$true)][string]$ModelDir
)
```

`build_local_agent_exe.ps1` 只调用 Worker 构建并把产物复制到同一 `dist/local-agent`，不把 Worker 重依赖收进 `local_agent.spec`。

- [ ] **Step 3: 固定第三方许可证清单**

记录 FFmpeg 构建、libvidstab、libx264、FunASR、PyTorch、YOLO、open_clip 和字体来源。缺少可分发依据时禁止形成客户安装包，但不阻塞源码级本地测试。

- [ ] **Step 4: 验证并提交**

```powershell
python -m pytest tests/test_phase12_ai_edit_packaging_contract.py -q
python -m PyInstaller --version
git diff --check
git add ai_edit_worker.spec requirements-ai-edit-worker.txt scripts/build_ai_edit_worker_exe.ps1 scripts/build_local_agent_exe.ps1 docs/ai/13_ai_edit/THIRD_PARTY_NOTICES.md tests/test_phase12_ai_edit_packaging_contract.py
git commit -m "构建：增加 AI剪辑 Worker 双运行时打包"
```

### 检查点 B：19000/Worker 安全边界

必须由 Spec Reviewer、Code Quality Reviewer、Security Reviewer 三方 PASS：

- 微信自动化与视频处理进程隔离，19000 路由和轮询不被阻塞。
- 取消能终止进程树，重启恢复不接受陈旧 attempt 回写。
- 本地路径、原始转写、模型原文和密钥不进入 9000/前端/普通日志。
- 原素材不变，Vid.Stab 保留音频，媒体强门有效。
- 安装包没有未履行许可证的第三方二进制。

三方 PASS 前不得进入 Task 9。

---

## Task 9：小高素材库与轻量剪辑前端

**Files:**
- Create: `frontend/src/features/ai-edit/types.ts`
- Create: `frontend/src/features/ai-edit/api.ts`
- Create: `frontend/src/features/ai-edit/localApi.ts`
- Create: `frontend/src/features/ai-edit/routes.ts`
- Modify: `frontend/src/features/routes.ts`
- Modify: `frontend/src/features/capabilities.ts`
- Modify: `frontend/src/pages/MaterialLibrary.tsx`
- Modify: `frontend/src/pages/AiVideoEditor.tsx`
- Create: `frontend/scripts/check-phase12-ai-edit-contract.mjs`

- [ ] **Step 1: 写前端合同红灯**

合同脚本断言：

- 两个页面进入 `auto_wechat:ai_edit` 导航。
- 不出现一键过审入口、假素材、假任务或假统计。
- 9000 API 与 `127.0.0.1:19000` Local API 分开。
- 页面存在导入、分析、增稳、取消、重试、720P 草稿、1080P 成片和回收站状态。

Run: `node frontend/scripts/check-phase12-ai-edit-contract.mjs`

Expected：因 AI剪辑功能目录、路由或页面合同尚未实现而退出非 0。

- [ ] **Step 2: 实现 API 和类型**

```typescript
export type AiEditJobStatus =
  | "queued" | "running" | "review_required"
  | "cancel_requested" | "cancelled" | "failed" | "succeeded";

export const LOCAL_AI_EDIT_BASE_URL = "http://127.0.0.1:19000";
```

Local API 复用现有本机 Agent token 处理方式；9000 API 复用 `apiClient`。

- [ ] **Step 3: 实现素材库**

私有素材、平台公共、回收站三个标签页；真实缩略图、状态、搜索和筛选；详情提供预览、分析、增稳、主动云端上传和删除。禁止嵌套卡片和说明型营销页面。

- [ ] **Step 4: 实现轻量剪辑工作台**

素材选择、模板、任务进度、片段列表、首尾时间、空镜替换、字幕编辑、字幕/BGM/增稳开关、720P 草稿和 1080P 确认。固定尺寸和响应式约束保证移动端/桌面不重叠。

- [ ] **Step 5: 验证并提交**

```powershell
node frontend/scripts/check-phase12-ai-edit-contract.mjs
cd frontend
npm.cmd run build
cd ..
git add frontend/src/features/ai-edit frontend/src/features/routes.ts frontend/src/features/capabilities.ts frontend/src/pages/MaterialLibrary.tsx frontend/src/pages/AiVideoEditor.tsx frontend/scripts/check-phase12-ai-edit-contract.mjs
git commit -m "功能：完成小高素材库与 AI 小高剪辑工作台"
```

---

## Task 10：本地/模拟闭环与阶段收口

**Files:**
- Create: `tests/test_phase12_ai_edit_e2e.py`
- Create: `tests/test_phase12_ai_edit_no_network.py`
- Create: `tests/test_phase12_ai_edit_final_contract.py`
- Create: `scripts/smoke_phase12_ai_edit_synthetic.py`
- Modify: `docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`
- Modify: `docs/ai/05_PROJECT_CONTEXT.md`
- Modify: `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md`

- [ ] **Step 1: 写端到端红灯**

模拟：9000 创建本地素材 ID -> 19000 导入 -> Worker 合成媒体链 -> 9100 规划替身 -> 720P review -> 人工调整 -> 1080P succeeded -> 下载。覆盖取消、重启恢复、跨商户、路径逃逸和旧 attempt 回写。

Run: `python -m pytest tests/test_phase12_ai_edit_e2e.py tests/test_phase12_ai_edit_no_network.py tests/test_phase12_ai_edit_final_contract.py -q`

Expected：新增合同探针应先证伪至少一个未闭合的集成缺口；若直接全绿，必须逐项检查测试是否真实经过 9000、19000、Worker 和 9100 替身边界，禁止把未执行链路误判为通过。

- [ ] **Step 2: 安装真实网络哨兵**

对 requests/httpx/urllib 安装局部计数哨兵；9100 客户端和 LLM 分别使用显式替身。任一未替换网络调用必须立即抛错，fixture 收尾再次断言调用次数为零；不得依赖生产代码吞掉 `AssertionError`。

```python
@pytest.fixture
def forbid_external_network(monkeypatch):
    calls: list[str] = []

    def blocked(kind: str):
        def _raise(*args, **kwargs):
            calls.append(kind)
            raise AssertionError(f"unexpected_external_network:{kind}")
        return _raise

    async def blocked_async(*args, **kwargs):
        calls.append("httpx_async")
        raise AssertionError("unexpected_external_network:httpx_async")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked("requests"))
    monkeypatch.setattr(httpx.Client, "request", blocked("httpx"))
    monkeypatch.setattr(httpx.AsyncClient, "request", blocked_async)
    monkeypatch.setattr(urllib.request, "urlopen", blocked("urllib"))
    yield calls
    assert calls == []
```

成功链路必须另外 monkeypatch `XgDouyinAiCsClient.plan_ai_edit` 和 9100 的 `OpenAICompatibleClient.chat`，返回严格 schema 固定值；不允许通过放开低层网络哨兵让测试通过。

- [ ] **Step 3: 运行合成媒体 smoke**

```powershell
python scripts/smoke_phase12_ai_edit_synthetic.py --output "$env:TEMP\phase12-ai-edit-smoke"
```

Expected：原素材哈希不变；720P/1080P 可探测；音频存在；字幕/空镜时间线不漂移；输出只写 smoke 目录。

- [ ] **Step 4: 执行全套回归**

```powershell
python -m pytest tests/test_phase12_ai_edit_schema.py tests/test_phase12_ai_edit_postgres_contract.py tests/test_phase12_ai_edit_api.py tests/test_phase12_ai_edit_service.py tests/test_phase12_ai_edit_planner.py tests/test_phase12_ai_edit_internal_api.py tests/test_phase12_ai_edit_worker_contract.py tests/test_phase12_ai_edit_core.py tests/test_phase12_ai_edit_media_tools.py tests/test_phase12_ai_edit_stabilizer.py tests/test_phase12_ai_edit_pipeline.py tests/test_phase12_local_ai_edit_storage.py tests/test_phase12_local_ai_edit_supervisor.py tests/test_phase12_local_ai_edit_routes.py tests/test_phase12_ai_edit_packaging_contract.py tests/test_phase12_ai_edit_e2e.py tests/test_phase12_ai_edit_no_network.py tests/test_phase12_ai_edit_final_contract.py -q
python -m pytest tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py tests/test_phase8b_poll_and_send_attachment.py tests/test_compute_usage_client.py tests/test_xiaogao_phase1_schema.py tests/test_db_migration_runner.py -q
node frontend/scripts/check-phase12-ai-edit-contract.mjs
cd frontend
npm.cmd run build
cd ..
git diff --check
```

- [ ] **Step 5: 执行本地真实素材人工验收**

在普通 Windows CPU 测试电脑上通过 UI 选择已授权汽车口播 MP4，完成导入、分析、可选增稳、9100 替身规划、轻量调整、720P 预览、1080P 成片和下载。确认原文件哈希不变、取消有效、重启可恢复。不得连接宝塔或真实付费模型。

- [ ] **Step 6: 同步文档状态**

仅在代码、自动化和本地人工验收均通过后更新：

```text
Phase 12 代码与本地/模拟闭环：DONE
Phase 12：DONE_WITH_CONCERNS
唯一 concern：baota_ai_edit_production_not_verified
宝塔生产验证：NOT_STARTED，Phase 13 后统一执行
```

- [ ] **Step 7: 提交**

```powershell
git add tests/test_phase12_ai_edit_e2e.py tests/test_phase12_ai_edit_no_network.py tests/test_phase12_ai_edit_final_contract.py scripts/smoke_phase12_ai_edit_synthetic.py docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md docs/ai/05_PROJECT_CONTEXT.md docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
git commit -m "测试：完成 Phase 12 AI剪辑本地闭环验收"
```

### 检查点 C：阶段总验收

必须由 Spec Reviewer、Code Quality Reviewer、Security Reviewer 三方 PASS：

- 设计第 2-15 节均有对应实现和自动化证据。
- 真实外部网络、宝塔、生产数据库和真实模型调用均为 0。
- 微信自动化安全门禁和 Phase 8/9/10 状态无回归。
- 本地素材不泄露，商户隔离、路径安全、取消、恢复和媒体强门有效。
- 前端不造假、不重叠，双分辨率真实产物可用。

三方 PASS 后 Phase 12 才可标记 `DONE_WITH_CONCERNS`，随后进入 Phase 13；不得提前启动宝塔验证。
