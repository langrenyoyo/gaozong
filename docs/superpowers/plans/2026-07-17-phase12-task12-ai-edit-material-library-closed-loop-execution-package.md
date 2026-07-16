# Phase 12 Task 12 AI 素材库真实闭环增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 闭合 AI 素材库回收站、导入后自动分析、宝塔受控云端上传和桌面/移动素材管理界面，并在检查点通过后重建单入口测试 EXE。

**Architecture:** 9000 继续作为素材 metadata、生命周期、分阶段状态、人工确认和云端文件权威源；19000 作为本机原素材真源，负责导入、自动分析队列、本地预览、增稳和文件流上传；9100 只接收 9000 转发的低清关键帧、转写和媒体摘要。前端不改现有导航、标题栏与模块切换，只重做其下方素材工作区。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite 顺序迁移、PostgreSQL Alembic、React 19、TypeScript、Vite、PyInstaller、Python 3.11 Worker、FFmpeg/ffprobe、FunASR、PySceneDetect/OpenCV 适配器、OpenAI-compatible 多模态消息。

**计划状态：** `READY_FOR_EXECUTION`。设计提交 `56faa8c`；生产验证保持 `NOT_STARTED`。

---

## 0. 总控边界

### 0.1 权威输入

- 批准规格：`docs/superpowers/specs/2026-07-16-phase12-task12-ai-edit-material-library-closed-loop-design.md`
- Phase 12 当前设计：`docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`
- 项目当前事实：`docs/ai/05_PROJECT_CONTEXT.md`
- `auto_edit` 多模态参考：`E:\work\project\auto_edit\docs\archive\reference\多模态模型能力和接口文档.md`
- `auto_edit` 来源代码只读：`E:\work\project\auto_edit`

不得把外部仓库加入运行时路径，不复制其环境文件、密钥、缓存、数据库、运行产物或完整视频上传实现。

### 0.2 硬禁止

- 不启动 Phase 13。
- 不连接宝塔真实目录、生产数据库、真实付费模型或抖音发布接口。
- 不修改全局导航、`AI小高剪辑` 标题栏、`ModuleTabs` 或剪辑工作台路由。
- 不恢复一键过审，不新增权限码。
- 不把 Local Agent token、内部令牌、绝对路径、存储键、转写原文或关键帧内容写入日志。
- 不把 `frontend/src/pages/MaterialLibrary.tsx` 旧占位页当作真实路由入口；真实入口是 `frontend/src/features/ai-edit/pages/MaterialLibrary.tsx`。

### 0.3 工作区保护

计划复审时已有用户改动：

```text
.gitignore
```

每个任务必须以当时 `git status` 为准继续记录新增脏文件。`.superpowers/` 是视觉稿生成目录，不得纳入业务提交。每个任务开始与提交前执行：

```powershell
git status --short
git diff --check
```

只 `git add` 当前任务白名单。不得暂存上述用户文件、`.superpowers/`、生成的 `.d.ts`、`frontend/dist/`、`build/` 或 `dist/`。

### 0.4 检查点

- Task 12-1 与 Task 12-2 连续执行；Task 12-2 后硬暂停检查点 A。
- 检查点 A 三方 PASS 后连续执行 Task 12-3 至 Task 12-6；Task 12-6 后硬暂停检查点 B。
- 检查点 B 三方 PASS 后连续执行 Task 12-7 至 Task 12-9；Task 12-9 后硬暂停检查点 C。
- 检查点 C 三方 PASS 后才允许 Task 12-10 重建测试 EXE。
- Must-Fix 使用 `Task 12-N-FIX1` 命名，提交后回到原检查点复审。

每个任务固定回传：提交哈希、精确文件、红灯、绿灯、关联回归、网络调用数、真实媒体调用范围、脏工作区保护、文档影响和残留风险。

### 0.5 测试环境

- Python 测试优先使用项目当前解释器：`python -m pytest ...`。
- Worker 真实构建固定 Python 3.11；Local Agent 与外层启动器固定 Python 3.10。
- 单元与端到端测试使用临时目录、替身模型和网络哨兵。
- 允许用合成媒体执行本机 FFmpeg/ffprobe；真实宝塔与真实模型调用数必须为 0。

---

## 1. 文件结构

### 1.1 数据与 9000

```text
app/models.py
app/schemas.py
app/routers/ai_edit.py
app/routers/admin_ai_edit.py
app/services/ai_edit_service.py
app/services/ai_edit_storage.py
app/services/xg_douyin_ai_cs_client.py
migrations/versions/0034_ai_edit_material_library.sql
migrations/downgrades/0034_ai_edit_material_library.sql
migrations/postgres/auto_wechat/versions/0015_ai_edit_material_library.py
```

### 1.2 19000 与 Worker

```text
apps/ai_edit/contracts.py
apps/ai_edit/material_analysis.py
apps/ai_edit/worker_main.py
app/local_agent_ai_edit_storage.py
app/local_agent_ai_edit_material_supervisor.py
app/local_agent_ai_edit_routes.py
app/local_agent_main.py
```

`material_analysis.py` 只负责可注入的单素材分析流水线；`local_agent_ai_edit_material_supervisor.py` 只负责分析/增稳素材操作队列、attempt、持久化和恢复。不得把素材操作状态塞入现有剪辑任务 `AiEditSupervisor`。

### 1.3 9100

```text
apps/xg_douyin_ai_cs/schemas.py
apps/xg_douyin_ai_cs/routers/ai_edit.py
apps/xg_douyin_ai_cs/services/ai_edit_safety.py
apps/xg_douyin_ai_cs/services/ai_edit_material_analysis_service.py
```

### 1.4 前端

```text
frontend/src/features/ai-edit/types.ts
frontend/src/features/ai-edit/api.ts
frontend/src/features/ai-edit/localApi.ts
frontend/src/features/ai-edit/pages/MaterialLibrary.tsx
frontend/src/pages/Index.tsx
frontend/src/features/ai-edit/components/MaterialFilters.tsx
frontend/src/features/ai-edit/components/MaterialGrid.tsx
frontend/src/features/ai-edit/components/MaterialDetail.tsx
frontend/src/features/ai-edit/components/MaterialTimeline.tsx
frontend/src/features/ai-edit/components/ImportQueue.tsx
frontend/scripts/check-phase12-task12-material-library-contract.mjs
frontend/scripts/check-phase12-task12-material-library-layout.mjs
```

---

## Task 12-1：冻结合同与红灯

**Files:**
- Create: `tests/test_phase12_task12_material_schema.py`
- Create: `tests/test_phase12_task12_material_api.py`
- Create: `tests/test_phase12_task12_material_analysis.py`
- Create: `tests/test_phase12_task12_material_cloud.py`
- Create: `frontend/scripts/check-phase12-task12-material-library-contract.mjs`

- [ ] **Step 1: 冻结 ORM 与迁移红灯**

在 `test_phase12_task12_material_schema.py` 固定：

```python
EXPECTED_MATERIAL_COLUMNS = {
    "display_name", "description", "category", "duration_seconds",
    "width", "height", "fps", "file_size_bytes",
    "manual_override_json", "manual_confirmed_at",
}
EXPECTED_STAGES = {
    "media_probe", "transcript", "content_analysis", "stability", "cloud_upload",
}

def test_task12_material_schema_contract():
    from app.models import AiEditMaterial, AiEditMaterialProcess
    assert EXPECTED_MATERIAL_COLUMNS <= set(AiEditMaterial.__table__.columns.keys())
    assert AiEditMaterialProcess.__tablename__ == "ai_edit_material_processes"

def test_task12_migration_files_exist():
    assert Path("migrations/versions/0034_ai_edit_material_library.sql").is_file()
    assert Path("migrations/downgrades/0034_ai_edit_material_library.sql").is_file()
    assert Path("migrations/postgres/auto_wechat/versions/0015_ai_edit_material_library.py").is_file()
```

- [ ] **Step 2: 冻结回收站、状态与去重红灯**

在 `test_phase12_task12_material_api.py` 用现有认证 fixture 建商户素材，固定：

```python
def test_list_trash_returns_only_deleted_materials(client, db, merchant_headers):
    active = seed_material(db, "mat-active", deleted=False)
    deleted = seed_material(db, "mat-trash", deleted=True)
    response = client.get(
        "/ai-edit/materials?scope=merchant&lifecycle=trash&page=1&page_size=20",
        headers=merchant_headers,
    )
    assert response.status_code == 200
    assert [item["material_id"] for item in response.json()["data"]["items"]] == [deleted.material_id]
    assert active.material_id not in response.text

def test_same_merchant_same_sha_returns_canonical_material(db):
    first = register(db, material_id="mat-a", sha="a" * 64)
    second = register(db, material_id="mat-b", sha="a" * 64)
    assert second.material_id == first.material_id
    assert db.query(AiEditMaterial).count() == 1
```

另固定跨商户同哈希可并存、平台只读、五阶段响应不含 `merchant_id/storage_key/absolute_path`。

- [ ] **Step 3: 冻结分析与云端红灯**

在分析与云端测试中固定：

```python
def test_reanalysis_preserves_manual_override(db):
    material = seed_confirmed_material(db, manual_tags=["人工标签"])
    save_ai_analysis(db, material, ai_tags=["AI 新标签"])
    detail = get_effective_material_detail(db, material.material_id)
    assert detail.tags[0] == "人工标签"

def test_cloud_upload_failure_keeps_local_only(tmp_path):
    service = make_storage_service(tmp_path)
    with pytest.raises(AiEditStorageError):
        service.store_stream("m1", "mat1", io.BytesIO(b"bad"), expected_size=4,
                             expected_sha256="0" * 64)
    assert service.temp_files() == []
```

- [ ] **Step 4: 冻结前端不可变区域与状态文案**

合同脚本读取真实页面源码并断言：

```javascript
assert.match(page, /<ModuleTabs/);
assert.match(page, /AI小高剪辑/);
assert.doesNotMatch(page, /pending[^\n]+处理中/);
assert.match(page, /私有素材/);
assert.match(page, /平台公共/);
assert.match(page, /回收站/);
assert.match(page, /MaterialDetail/);
assert.match(page, /ImportQueue/);
```

- [ ] **Step 5: 运行红灯并提交**

```powershell
python -m pytest tests/test_phase12_task12_material_schema.py tests/test_phase12_task12_material_api.py tests/test_phase12_task12_material_analysis.py tests/test_phase12_task12_material_cloud.py -q
node frontend/scripts/check-phase12-task12-material-library-contract.mjs
```

Expected：因 `AiEditMaterialProcess`、0034/0015、回收站查询、自动分析、云端存储和新组件缺失而失败；不得出现 fixture 导入错误。

```powershell
git add tests/test_phase12_task12_material_schema.py tests/test_phase12_task12_material_api.py tests/test_phase12_task12_material_analysis.py tests/test_phase12_task12_material_cloud.py frontend/scripts/check-phase12-task12-material-library-contract.mjs
git commit -m "测试：冻结 Task 12 素材库真实闭环合同"
```

---

## Task 12-2：数据模型与双轨迁移

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Create: `migrations/versions/0034_ai_edit_material_library.sql`
- Create: `migrations/downgrades/0034_ai_edit_material_library.sql`
- Create: `migrations/postgres/auto_wechat/versions/0015_ai_edit_material_library.py`
- Modify: `tests/test_phase12_task12_material_schema.py`

- [ ] **Step 1: 补 ORM 与公共 DTO**

核心模型必须等价于：

```python
class AiEditMaterialProcess(Base):
    __tablename__ = "ai_edit_material_processes"
    __table_args__ = (
        UniqueConstraint("material_id", "source_sha256", "stage",
                         name="uk_ai_edit_material_process_stage"),
        CheckConstraint("stage IN ('media_probe','transcript','content_analysis','stability','cloud_upload')",
                        name="ck_ai_edit_material_process_stage"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','not_required')",
                        name="ck_ai_edit_material_process_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_ai_edit_material_process_progress"),
        CheckConstraint("attempt_count >= 0", name="ck_ai_edit_material_process_attempt"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(String(64), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    stage = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    progress = Column(Integer, nullable=False, server_default="0")
    attempt_count = Column(Integer, nullable=False, server_default="0")
    failure_code = Column(String(64))
    error_summary = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
```

`AiEditMaterial` 增加规格中的 10 列，并增加 `(merchant_id, source_sha256)` 唯一约束。`AiEditMaterialOut` 只增加安全展示与媒体字段以及 `processes: list[AiEditMaterialProcessOut]`，不得暴露内部键。

- [ ] **Step 2: 写 SQLite 0034 升降级**

升级脚本在任何 `RENAME` 前执行：

```sql
CREATE TEMP TABLE _guard_0034 (ok INTEGER NOT NULL CHECK (ok = 1));

INSERT INTO _guard_0034 (ok)
SELECT CASE WHEN NOT EXISTS (
    SELECT 1
    FROM ai_edit_materials
    WHERE merchant_id IS NOT NULL
    GROUP BY merchant_id, source_sha256
    HAVING count(*) > 1
) THEN 1 ELSE 0 END;

INSERT INTO _guard_0034 (ok)
SELECT CASE WHEN (
    SELECT max(version_num) FROM schema_migrations
) = '0033' THEN 1 ELSE 0 END;

DROP TABLE _guard_0034;
```

使用 `pragma_table_xinfo` 固定 0033 的 17 个普通列和无隐藏列；重建 `ai_edit_materials` 时逐列复制旧数据，新列保持 `NULL`。用包含 `id`、时间字段和全部旧业务列的双向 `EXCEPT` 与行数守卫证明无损。创建 `ai_edit_material_processes`、索引和版本登记。

降级只在 head 精确为 `0034` 时执行，拒绝未知列、隐藏列和后续版本；恢复 0033 的 17 列并保留全部旧数据。

- [ ] **Step 3: 写 PostgreSQL 0015**

```python
revision = "0015_ai_edit_material_library"
down_revision = "0014_compute_usage_measurement"
```

`upgrade()` 只 `add_column/create_table/create_index/create_unique_constraint`，不 `create_all`。`downgrade()` 只删除 0015 自身对象。历史重复 `(merchant_id, source_sha256)` 用前置 SQL 检查抛错，不删除或合并历史行。

- [ ] **Step 4: 运行数据合同与迁移回归**

```powershell
python -m pytest tests/test_phase12_task12_material_schema.py tests/test_phase12_ai_edit_schema.py tests/test_phase12_ai_edit_postgres_contract.py tests/test_compute_usage_measurement_sqlite_migration.py tests/test_db_migration_runner.py -q
```

Expected：Task 12 数据合同全绿；既有迁移回归无新增失败。

- [ ] **Step 5: 提交并硬暂停检查点 A**

```powershell
git add app/models.py app/schemas.py migrations/versions/0034_ai_edit_material_library.sql migrations/downgrades/0034_ai_edit_material_library.sql migrations/postgres/auto_wechat/versions/0015_ai_edit_material_library.py tests/test_phase12_task12_material_schema.py
git commit -m "功能：增加 Task 12 素材库数据迁移"
```

检查点 A 回传必须逐项证明：历史素材无损、重复数据显式拒绝、升级失败整体回滚、降级可再次升级、PG revision 链正确、公共 DTO 无路径/存储键/商户 ID。未获规范、数据库、安全三方 PASS 前不得进入 Task 12-3。

---

## Task 12-3：9000 素材控制面

**Files:**
- Modify: `app/services/ai_edit_service.py`
- Modify: `app/routers/ai_edit.py`
- Create: `app/routers/admin_ai_edit.py`
- Modify: `app/main.py`
- Modify: `app/schemas.py`
- Modify: `tests/test_phase12_task12_material_api.py`
- Modify: `tests/test_phase12_ai_edit_api.py`
- Modify: `tests/test_phase12_ai_edit_service.py`

- [ ] **Step 1: 先补查询、去重和脱敏红灯**

增加精确测试：活跃/回收站互斥、页码与总数、关键词/分类/阶段筛选、跨商户 404、平台只读、非超管访问 `/admin/ai-edit/materials` 得 403、同商户 SHA 并发冲突恢复、公共响应键集脱敏。

- [ ] **Step 2: 实现列表与规范 ID 去重**

服务签名固定为：

```python
def list_materials(db: Session, *, merchant_id: str, scope: str,
                   lifecycle: str, query: str | None, category: str | None,
                   stage: str | None, process_status: str | None,
                   page: int, page_size: int) -> tuple[int, list[AiEditMaterial]]:
    q = db.query(AiEditMaterial)
    if lifecycle == "trash":
        q = q.filter(
            AiEditMaterial.deleted_at.isnot(None),
            AiEditMaterial.purge_after.isnot(None),
        )
    else:
        q = q.filter(AiEditMaterial.deleted_at.is_(None))
    q = q.filter(AiEditMaterial.scope == scope)
    if scope == "merchant":
        q = q.filter(AiEditMaterial.merchant_id == merchant_id)
    if query:
        latest_ids = db.query(
            AiEditMaterialAnalysis.material_id,
            func.max(AiEditMaterialAnalysis.id).label("analysis_id"),
        ).group_by(AiEditMaterialAnalysis.material_id).subquery()
        q = q.outerjoin(latest_ids, latest_ids.c.material_id == AiEditMaterial.material_id)
        q = q.outerjoin(AiEditMaterialAnalysis,
                        AiEditMaterialAnalysis.id == latest_ids.c.analysis_id)
        like = f"%{query}%"
        q = q.filter(or_(AiEditMaterial.display_name.ilike(like),
                         AiEditMaterial.description.ilike(like),
                         AiEditMaterialAnalysis.transcript_json.ilike(like)))
    if category:
        q = q.filter(AiEditMaterial.category == category)
    if stage and process_status:
        q = q.join(AiEditMaterialProcess).filter(
            AiEditMaterialProcess.stage == stage,
            AiEditMaterialProcess.status == process_status,
        )
    total = q.count()
    return total, q.order_by(AiEditMaterial.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
```

标签筛选只匹配最新分析快照的规范 JSON 标签值和人工覆盖标签；时长、创建时间与排序在数据库查询阶段完成，禁止先分页再用 Python 过滤。为 `scope/lifecycle/category/stage/status/min_duration/max_duration/created_from/created_to/sort` 各写至少一个合同断言。

`register_material` 先按 `(merchant_id, source_sha256)` 回查全部历史行：活动行直接返回规范 ID；回收站或 `purge_after=NULL` 的已清理 tombstone 使用同一规范 ID 复活并清除删除字段；不得插入第二行。并发首次写入捕获唯一约束 `IntegrityError` 后同样按该组合回查。

Local Agent 可信注册请求允许可选 `parent_material_id`，仅用于增稳衍生素材；服务必须验证父素材属于同一商户且未删除，普通商户注册接口不得自报该字段。

- [ ] **Step 3: 实现阶段状态、分析快照和人工确认**

```python
def update_material_process(db, *, material, stage, status, progress,
                            attempt_count, failure_code=None, error_summary=None):
    row = db.query(AiEditMaterialProcess).filter_by(
        material_id=material.material_id,
        source_sha256=material.source_sha256,
        stage=stage,
    ).one_or_none()
    if row is None:
        row = AiEditMaterialProcess(
            material_id=material.material_id,
            source_sha256=material.source_sha256,
            stage=stage,
            status="queued",
            progress=0,
            attempt_count=0,
        )
        db.add(row)
    if attempt_count < row.attempt_count:
        raise AiEditStatusConflict("STALE_MATERIAL_ATTEMPT")
    row.status, row.progress, row.attempt_count = status, progress, attempt_count
    row.failure_code = failure_code
    row.error_summary = redact_sensitive_text(error_summary)
    row.completed_at = datetime.now() if status in {"succeeded", "failed", "not_required"} else None
    db.flush()
    return row
```

分析 JSON 先经 Pydantic 严格模型校验再写 `AiEditMaterialAnalysis`。详情组装按 `manual_override_json > 最新分析 > 空值` 合并，重新分析不得修改人工字段。

- [ ] **Step 4: 实现商户与超管路由**

`GET /ai-edit/materials` 使用显式 `Query` 参数；增加详情、缩略图、人工确认和 Local Agent 阶段/分析写入接口。新建 `admin_ai_edit.py`，固定前缀 `/admin/ai-edit`，仅 `context.super_admin` 可维护平台公共素材；`app/main.py` 只注册该路由，不改其他路由顺序或生命周期。不新增权限码。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/test_phase12_task12_material_api.py tests/test_phase12_ai_edit_api.py tests/test_phase12_ai_edit_service.py tests/test_local_agent_auth.py -q
git add app/services/ai_edit_service.py app/routers/ai_edit.py app/routers/admin_ai_edit.py app/main.py app/schemas.py tests/test_phase12_task12_material_api.py tests/test_phase12_ai_edit_api.py tests/test_phase12_ai_edit_service.py
git commit -m "功能：闭合 9000 素材控制面"
```

---

## Task 12-4：19000 自动分析流水线

**Files:**
- Modify: `apps/ai_edit/contracts.py`
- Create: `apps/ai_edit/material_analysis.py`
- Modify: `apps/ai_edit/worker_main.py`
- Create: `app/local_agent_ai_edit_material_supervisor.py`
- Modify: `app/local_agent_ai_edit_storage.py`
- Modify: `app/local_agent_ai_edit_routes.py`
- Modify: `app/local_agent_main.py`
- Modify: `tests/test_phase12_task12_material_analysis.py`
- Create: `tests/test_phase12_local_material_supervisor.py`

- [ ] **Step 1: 写纯分析与恢复红灯**

固定 `phase12_material_operation_v1` 清单只含操作类型、相对路径、素材 ID、源 SHA 和 attempt；结果只含媒体摘要、转写、场景、关键帧相对路径、稳定性或衍生素材结果和稳定错误码。增加分析/增稳重启恢复、旧 attempt 拒绝、导入后自动排队、原素材哈希不变、`source_path` 不出结果/日志测试。

- [ ] **Step 2: 实现 Worker 分析合同和纯流水线**

```python
class MaterialOperationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["phase12_material_operation_v1"]
    operation: Literal["analyze", "stabilize"]
    material_id: str = Field(..., min_length=1, max_length=64)
    attempt_count: int = Field(..., ge=0)
    task_root: Path
    relative_path: str
    source_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    output_relative_path: str | None = None

    @model_validator(mode="after")
    def validate_operation_output(self):
        if self.operation == "stabilize" and not self.output_relative_path:
            raise ValueError("增稳操作必须提供受管输出相对路径")
        return self

@dataclass
class MaterialAnalysisDeps:
    probe: Callable[[Path], dict]
    transcribe: Callable[[Path, float], list[dict]]
    split_scenes: Callable[[Path], list[dict]]
    extract_keyframe: Callable[[Path, float, Path], None]
    measure_stability: Callable[[Path], dict]
```

`run_material_analysis` 逐阶段调用依赖并写原子 `material-result.json`。关键帧最大边 720px、JPEG、每场景 1 张、总数最多 12。迁入 `auto_edit` 时只复制解析/适配器逻辑，移除 `source_path` 和原始 stdout/stderr。

生产依赖不得调用未保证存在的 `funasr` 或 `scenedetect` 命令：

```python
def build_local_transcriber(model_dir: Path):
    if not model_dir.is_dir() or not (model_dir / "configuration.json").is_file():
        raise MaterialAnalysisError("ASR_MODEL_NOT_AVAILABLE")
    from funasr import AutoModel
    model = AutoModel(model=str(model_dir), disable_update=True)
    return lambda audio_path: model.generate(input=str(audio_path))

def split_scenes_with_pyscenedetect(video_path: Path) -> list[dict]:
    from scenedetect import ContentDetector, SceneManager, open_video
    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector())
    manager.detect_scenes(video)
    return [
        {"start": start.get_seconds(), "end": end.get_seconds()}
        for start, end in manager.get_scene_list()
    ]
```

`AI_EDIT_ASR_MODEL_DIR` 只能指向随包本地目录，`disable_update=True` 且网络哨兵必须证明不下载模型。ASR 失败只把 transcript 阶段标记失败；场景、关键帧和稳定性继续执行。

- [ ] **Step 3: 实现独立持久化监督器**

`MaterialOperationSupervisor` 使用 `(merchant_id, material_id, operation)` 复合键，状态文件只存受管相对清单路径、attempt 和状态。`enqueue()` 原子持久化后入队；`recover()` 把 `queued/running` 归一为新 attempt 的 `queued`；`writeback()` 拒绝旧 attempt。

- [ ] **Step 4: 接入导入链路和生产 Worker**

19000 导入完成并成功同步 9000 后立即创建 `operation=analyze` 清单并 `enqueue`。`worker_main.main()` 根据 `schema_version` 分派素材操作或既有剪辑流水线；不得破坏现有剪辑 manifest。素材操作复用现有 `_ai_edit_executor` 的参数数组、独立进程组、管道有界读取和凭据环境剥离，不另写子进程启动器。终态回调逐阶段写回 9000，网络失败保留 `pending_writeback`，重启补偿。

一键增稳创建 `operation=stabilize` 清单，调用现有 `apps.ai_edit.stabilizer.stabilize`，输出到新的受管素材目录。完成后再次校验原素材 SHA-256 未变化、衍生文件可被 ffprobe 读取，再以新素材 ID 和可信 `parent_material_id` 注册 9000。失败时删除衍生临时文件，不修改原素材与父素材记录。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/test_phase12_task12_material_analysis.py tests/test_phase12_local_material_supervisor.py tests/test_phase12_ai_edit_worker_contract.py tests/test_phase12_ai_edit_stabilizer.py tests/test_phase12_local_ai_edit_routes.py tests/test_phase12_local_ai_edit_supervisor.py -q
git add apps/ai_edit/contracts.py apps/ai_edit/material_analysis.py apps/ai_edit/worker_main.py app/local_agent_ai_edit_material_supervisor.py app/local_agent_ai_edit_storage.py app/local_agent_ai_edit_routes.py app/local_agent_main.py tests/test_phase12_task12_material_analysis.py tests/test_phase12_local_material_supervisor.py
git commit -m "功能：增加本机素材自动分析流水线"
```

---

## Task 12-5：9100 多模态语义分析

**Files:**
- Modify: `apps/xg_douyin_ai_cs/schemas.py`
- Modify: `apps/xg_douyin_ai_cs/routers/ai_edit.py`
- Create: `apps/xg_douyin_ai_cs/services/ai_edit_safety.py`
- Modify: `apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py`
- Create: `apps/xg_douyin_ai_cs/services/ai_edit_material_analysis_service.py`
- Modify: `app/services/xg_douyin_ai_cs_client.py`
- Modify: `app/services/ai_edit_service.py`
- Create: `tests/test_phase12_task12_material_semantic.py`
- Modify: `tests/test_phase12_ai_edit_internal_api.py`

- [ ] **Step 1: 写严格协议、注入与零泄露红灯**

固定 `extra=forbid`、最多 12 张 JPEG/WEBP 关键帧、单帧 base64 解码后不超过 512KB、最多 100 条转写、所有区间在媒体时长内。测试请求中出现本地路径、原视频字段、未知素材 ID、提示词注入或越界区间时稳定拒绝。

- [ ] **Step 2: 实现严格 schema**

```python
import base64
import binascii

class MaterialKeyframe(BaseModel):
    model_config = {"extra": "forbid"}
    scene_id: str = Field(..., min_length=1, max_length=64)
    at_seconds: float = Field(..., ge=0)
    mime_type: Literal["image/jpeg", "image/webp"]
    content_base64: str = Field(..., min_length=1, max_length=700_000)

    @field_validator("content_base64")
    @classmethod
    def validate_frame_bytes(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("关键帧不是合法 base64") from exc
        if len(decoded) > 512 * 1024:
            raise ValueError("关键帧解码后不得超过 512KB")
        return value

class MaterialSemanticAnalysisRequest(BaseModel):
    model_config = {"extra": "forbid"}
    merchant_id: str = Field(..., min_length=1, max_length=128)
    material_id: str = Field(..., min_length=1, max_length=64)
    duration_seconds: float = Field(..., gt=0)
    transcript: list[TranscriptSegment] = Field(default_factory=list, max_length=100)
    scenes: list[SceneSummary] = Field(..., min_length=1, max_length=100)
    keyframes: list[MaterialKeyframe] = Field(..., min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_timeline(self):
        if any(frame.at_seconds > self.duration_seconds for frame in self.keyframes):
            raise ValueError("关键帧时间不得超过素材时长")
        return self
```

响应固定 `description/category/tags/highlights/usable_ranges/confidence/model/prompt_version`，分类只允许 `spoken/broll/highlight/uncategorized`。

- [ ] **Step 3: 抽取最小共享注入检查**

把 `ai_edit_planner_service.py` 现有冻结模式原位移动到 `ai_edit_safety.py`，对外只暴露文本列表接口：

```python
def contains_prompt_injection(values: list[str]) -> bool:
    normalized = "\n".join(str(value or "").lower() for value in values)
    return any(pattern.search(normalized) for pattern in INJECTION_PATTERNS)
```

规划服务改为传入转写和镜头标签；素材分析服务传入转写文本和场景标签。先跑既有 planner 注入测试，证明行为不变。

- [ ] **Step 4: 实现一次多模态调用和严格解析**

服务构造 OpenAI-compatible `content` 数组：一段结构化文本和每张关键帧的 `data:image/...;base64,...`。只调用一次 `OpenAICompatibleClient.chat()`；先复用既有注入检测，再 `json.loads` 和 Pydantic 校验。拒答、空输出、格式错误、越界结果分别返回稳定错误码，不生成规则兜底。

成功 HTTP 调用后按既有 planner 模式优先使用供应商 `usage.total_tokens` 上报 `capability_key="compute"`；供应商无 usage 时只用文本消息与回复估算，不把 base64 图片放入计费 payload 或日志。

- [ ] **Step 5: 接通 9000 窄客户端**

```python
def analyze_ai_edit_material(self, request: dict) -> dict:
    return self._post_json("/internal/ai-edit/materials/analyze", request)
```

9000 从可信素材和本地分析结果构造请求，成功后保存版本化快照；9100 失败只把 `content_analysis` 标为 `failed`，不回滚其他阶段。

- [ ] **Step 6: 运行并提交**

```powershell
python -m pytest tests/test_phase12_task12_material_semantic.py tests/test_phase12_ai_edit_internal_api.py tests/test_phase12_ai_edit_planner.py tests/test_compute_usage_client.py -q
git add apps/xg_douyin_ai_cs/schemas.py apps/xg_douyin_ai_cs/routers/ai_edit.py apps/xg_douyin_ai_cs/services/ai_edit_safety.py apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py apps/xg_douyin_ai_cs/services/ai_edit_material_analysis_service.py app/services/xg_douyin_ai_cs_client.py app/services/ai_edit_service.py tests/test_phase12_task12_material_semantic.py tests/test_phase12_ai_edit_internal_api.py
git commit -m "功能：增加素材多模态语义分析"
```

---

## Task 12-6：9000 宝塔受控云端存储

**Files:**
- Modify: `app/services/ai_edit_storage.py`
- Modify: `app/routers/ai_edit.py`
- Modify: `app/local_agent_ai_edit_routes.py`
- Modify: `app/local_agent_main.py`
- Modify: `app/config.py`
- Modify: `.env.development.example`
- Modify: `.env.lan.example`
- Modify: `.env.production.example`
- Modify: `tests/test_phase12_task12_material_cloud.py`
- Create: `tests/test_phase12_task12_material_preview.py`

- [ ] **Step 1: 写原子上传、Range 与商户隔离红灯**

覆盖大小不符、SHA 不符、断流、符号链接、中间目录重解析点、跨商户、重复上传幂等、`Range: bytes=0-99` 返回 206、无本地/云端文件返回稳定错误。

- [ ] **Step 2: 实现流式原子存储**

```python
from collections.abc import AsyncIterable
from dataclasses import dataclass

@dataclass(frozen=True)
class StoredMaterial:
    storage_key: str
    size_bytes: int
    sha256: str

def build_material_storage_key(merchant_id: str, material_id: str, suffix: str) -> str:
    if (not material_id or material_id.startswith(".")
            or any(char in material_id for char in "/\\:")):
        raise AiEditStorageError("MATERIAL_ID_INVALID")
    merchant_key = hashlib.sha256(merchant_id.encode("utf-8")).hexdigest()[:24]
    clean_suffix = suffix.lower().lstrip(".")
    if clean_suffix not in {"mp4", "mov", "avi", "jpg", "jpeg", "png", "webp"}:
        raise AiEditStorageError("MATERIAL_SUFFIX_NOT_ALLOWED")
    return f"materials/{merchant_key}/{material_id}/source.{clean_suffix}"

async def store_material_stream(*, root: Path, merchant_id: str, material_id: str,
                                chunks: AsyncIterable[bytes], expected_size: int,
                                expected_sha256: str, suffix: str) -> StoredMaterial:
    storage_key = build_material_storage_key(merchant_id, material_id, suffix)
    target = resolve_ai_edit_storage_key(storage_key, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".upload_", dir=target.parent)
    digest, total = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as output:
            async for chunk in chunks:
                if not chunk:
                    continue
                output.write(chunk)
                digest.update(chunk)
                total += len(chunk)
        if total != expected_size or digest.hexdigest() != expected_sha256:
            raise AiEditStorageError("MATERIAL_UPLOAD_INTEGRITY_FAILED")
        os.replace(temp_name, target)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return StoredMaterial(storage_key=storage_key, size_bytes=total,
                          sha256=digest.hexdigest())
```

9000 路由使用 `async for` 的 `Request.stream()` 直接传给该函数。存储键使用不可逆商户哈希目录，不把明文 `merchant_id` 放进存储键。检查每个现存父目录均非符号链接/重解析点。

- [ ] **Step 3: 实现 19000 到 9000 流式上传**

`Nine000ControlClient.upload_material` 接收本机受管 `Path`，生产实现用标准库 `http.client` 发送原始请求体：

```python
connection.putrequest("PUT", upload_path)
connection.putheader("Content-Length", str(source.stat().st_size))
connection.putheader("X-Content-SHA256", expected_sha256)
connection.putheader("X-Local-Agent-Token", self.token)
connection.endheaders()
with source.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        connection.send(chunk)
response = connection.getresponse()
```

不得 `read_bytes()`。9000 收流时状态为 `running`，原子提交后才写 `cloud_available/succeeded`。

- [ ] **Step 4: 实现云端预览和本地短票据**

9000 云端内容接口支持单区间 Range、`Accept-Ranges: bytes` 和登录态商户隔离。本地预览先用带 Local Agent token 的 JSON 请求签发 60 秒随机票据，再由 `<video>` 使用票据 URL；票据只绑定商户、素材和到期时间，Local Agent access log 不记录票据值。

由于 `<video>` 会连续发多个 Range 请求，票据在 60 秒内允许同素材重复使用，不能首请求即销毁。`app/local_agent_main.py` 给 `uvicorn.access` 增加窄过滤器，只对本地预览路径移除 query：

```python
class LocalPreviewAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            path = str(args[2])
            if path.startswith("/agent/ai-edit/materials/preview?"):
                args[2] = path.split("?", 1)[0] + "?ticket=[REDACTED]"
                record.args = tuple(args)
        return True
```

测试捕获 `uvicorn.access`，断言随机票据原值不在日志。预览 `OPTIONS/GET` 继续使用现有回环 CORS/PNA 策略。

Range 解析使用独立纯函数，拒绝多区间和越界：

```python
def parse_single_range(header: str | None, size: int) -> tuple[int, int]:
    if size <= 0:
        raise AiEditStorageError("RANGE_NOT_SATISFIABLE")
    if not header:
        return 0, size - 1
    if not header.startswith("bytes=") or "," in header:
        raise AiEditStorageError("RANGE_NOT_SATISFIABLE")
    start_text, end_text = header[6:].split("-", 1)
    try:
        if not start_text:
            length = int(end_text)
            if length <= 0:
                raise AiEditStorageError("RANGE_NOT_SATISFIABLE")
            return max(0, size - length), size - 1
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    except ValueError as exc:
        raise AiEditStorageError("RANGE_NOT_SATISFIABLE") from exc
    if start < 0 or start >= size or end < start:
            raise AiEditStorageError("RANGE_NOT_SATISFIABLE")
    return start, min(end, size - 1)
```

- [ ] **Step 5: 配置与测试**

新增 `AI_EDIT_CLOUD_STORAGE_ROOT`，开发/局域网/生产示例均为空或测试路径说明，不写客户真实路径。运行：

```powershell
python -m pytest tests/test_phase12_task12_material_cloud.py tests/test_phase12_task12_material_preview.py tests/test_phase12_ai_edit_api.py tests/test_phase12_local_ai_edit_routes.py -q
```

- [ ] **Step 6: 提交并硬暂停检查点 B**

```powershell
git add app/services/ai_edit_storage.py app/routers/ai_edit.py app/local_agent_ai_edit_routes.py app/local_agent_main.py app/config.py .env.development.example .env.lan.example .env.production.example tests/test_phase12_task12_material_cloud.py tests/test_phase12_task12_material_preview.py
git commit -m "功能：增加 AI 素材受控云端存储"
```

检查点 B 必须证明：原视频只在主动上传时离开本机；多模态只发低清帧和转写；上传不整文件入内存；断流无半文件；Range 正确；商户隔离；日志脱敏；真实外网、宝塔和付费模型调用均为 0。

---

## Task 12-7：回收站、恢复与跨端清理

**Files:**
- Create: `app/scheduler/ai_edit_material_cleanup_scheduler.py`
- Modify: `app/main.py`
- Modify: `app/services/ai_edit_service.py`
- Modify: `app/routers/ai_edit.py`
- Modify: `app/local_agent_ai_edit_storage.py`
- Modify: `app/local_agent_ai_edit_routes.py`
- Modify: `app/local_agent_main.py`
- Modify: `app/config.py`
- Modify: `.env.development.example`
- Modify: `.env.lan.example`
- Modify: `.env.production.example`
- Create: `tests/test_phase12_task12_material_lifecycle.py`
- Create: `tests/test_phase12_task12_cleanup_scheduler.py`

- [ ] **Step 1: 写恢复、永久删除和离线补偿红灯**

覆盖：恢复后重新出现在 active；永久删除活动引用得 409；回收期保留本地/云端；到期后 9000 清云端并把 `purge_after` 置空形成不可见 tombstone；19000 按本地清单的 `purge_after` 在下次启动清本机；重复恢复/清理幂等；跨商户 404。

- [ ] **Step 2: 实现本地生命周期原语**

```python
def restore_material(root: Path, material_id: str) -> MaterialRecord:
    record = next(
        (item for item in list_materials(root) if item.material_id == material_id),
        None,
    )
    if record is None:
        raise LocalAiEditStorageError("MATERIAL_NOT_FOUND")
    record.deleted_at = None; record.purge_after = None
    _upsert_manifest(root, record)
    return record

def purge_material(root: Path, material_id: str) -> None:
    if _load_active_refs(root).get(material_id):
        raise LocalAiEditStorageError("MATERIAL_HAS_ACTIVE_REFERENCE")
    path = resolve_managed_material_path(root, material_id)
    path.unlink(missing_ok=True)
    _remove_manifest_record(root, material_id)

def _remove_manifest_record(root: Path, material_id: str) -> None:
    data = _load_manifest(root)
    data["materials"] = [
        item for item in data.get("materials", [])
        if item.get("material_id") != material_id
    ]
    _save_manifest_atomic(root, data)
```

只删除受管文件和已验证为空的素材目录，拒绝递归删除商户根。

- [ ] **Step 3: 实现 19000 协调与 9000 幂等状态机**

恢复顺序：本地恢复 → 9000 恢复；9000 失败则用操作前 `deleted_at/purge_after` 快照回滚本地软删。永久删除顺序：9000 prepare 校验活动引用 → 本地清理 → 9000 finalize 再校验并删除云端、清空 `purge_after/cloud_storage_key`、置 `storage_mode=local_missing`，保留不可见审计 tombstone。prepare 后素材保持已删除，不能产生新任务引用；任一步重试使用同一 `operation_id`，不新增状态枚举或签名密钥。

- [ ] **Step 4: 实现有界清理调度器**

`AiEditMaterialCleanupScheduler` 复用现有 scheduler 的 `start/stop/run_once` 形态，每次最多处理 `AI_EDIT_MATERIAL_CLEANUP_BATCH_SIZE` 条到期素材。9000 只清理云端并保留 tombstone；19000 启动时独立扫描本地清单清理到期文件，两端都按 `purge_after` 幂等收敛，不需要新增跨端状态。默认开发关闭，生产示例仍保持 `false`，Phase 13 配置窗口显式开启。`run_once()` 可在本地测试直接调用；单条失败不阻断批次。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/test_phase12_task12_material_lifecycle.py tests/test_phase12_task12_cleanup_scheduler.py tests/test_9000_async_pg_lifecycle.py tests/test_phase12_local_ai_edit_storage.py tests/test_phase12_local_ai_edit_routes.py -q
git add app/scheduler/ai_edit_material_cleanup_scheduler.py app/main.py app/services/ai_edit_service.py app/routers/ai_edit.py app/local_agent_ai_edit_storage.py app/local_agent_ai_edit_routes.py app/local_agent_main.py app/config.py .env.development.example .env.lan.example .env.production.example tests/test_phase12_task12_material_lifecycle.py tests/test_phase12_task12_cleanup_scheduler.py
git commit -m "功能：闭合 AI 素材回收站与到期清理"
```

---

## Task 12-8：素材库桌面与移动前端

**Files:**
- Modify: `frontend/src/features/ai-edit/types.ts`
- Modify: `frontend/src/features/ai-edit/api.ts`
- Modify: `frontend/src/features/ai-edit/localApi.ts`
- Modify: `frontend/src/features/ai-edit/pages/MaterialLibrary.tsx`
- Modify: `frontend/src/pages/Index.tsx`
- Create: `frontend/src/features/ai-edit/components/MaterialFilters.tsx`
- Create: `frontend/src/features/ai-edit/components/MaterialGrid.tsx`
- Create: `frontend/src/features/ai-edit/components/MaterialDetail.tsx`
- Create: `frontend/src/features/ai-edit/components/MaterialTimeline.tsx`
- Create: `frontend/src/features/ai-edit/components/ImportQueue.tsx`
- Modify: `frontend/scripts/check-phase12-task12-material-library-contract.mjs`
- Create: `frontend/scripts/check-phase12-task12-material-library-layout.mjs`

- [ ] **Step 1: 扩展真实类型与 API**

```typescript
export type MaterialProcessStage =
  | "media_probe" | "transcript" | "content_analysis" | "stability" | "cloud_upload";
export type MaterialProcessStatus = "queued" | "running" | "succeeded" | "failed" | "not_required";
export interface AiEditMaterialProcess {
  stage: MaterialProcessStage;
  status: MaterialProcessStatus;
  progress: number;
  failure_code: string | null;
  error_summary: string | null;
}
```

9000 API 增加带筛选分页的列表、详情、缩略图、人工确认；19000 API 增加分析、上传、增稳、恢复、永久删除和预览票据。所有 Local API 都要求显式 `merchantId`。

- [ ] **Step 2: 实现页面组件**

`MaterialLibrary.tsx` 只编排状态与数据请求；筛选、网格、详情、时间轴、导入队列各自独立。`Index.tsx` 只用现有 `isSuperAdmin(user)` helper 计算布尔值并传给素材库，不新增用户字段，不修改全局导航或路由分发。保留现有 header 与：

```tsx
<ModuleTabs items={[
  { label: "素材库", path: "/ai-edit/materials" },
  { label: "剪辑工作台", path: "/ai-edit/editor" },
]} />
```

内容区桌面使用 `grid-template-columns: 196px minmax(0,1fr) 360px`；移动端小于 768px 改单栏，筛选抽屉和全屏详情。颜色只使用现有 `#f3f6fa/#e4e8f0/#1a1f2e/#2563eb` 及既有状态色。

- [ ] **Step 3: 实现真实导入和批量操作**

文件选择器同时支持 `multiple` 与文件夹入口；拖拽复用同一队列。队列逐项保存 `validating/deduplicating/importing/queued/succeeded/failed/existing`。批量操作以并发上限 2 调单素材接口并保留逐项错误，禁止 `Promise.all` 任一失败导致整批丢失。

- [ ] **Step 4: 实现预览、状态与人工确认**

本地可用时请求短票据，云端可用时走 9000 内容接口。卡片只显示两个最高优先级状态；详情展示五阶段。`queued` 显示“待处理”，不得把 `pending` 显示为“处理中”。时间轴只允许在 `0 <= start < end <= duration` 内编辑，保存后标记“人工确认”。

- [ ] **Step 5: 运行合同、构建与布局检查**

```powershell
node frontend/scripts/check-phase12-task12-material-library-contract.mjs
npm --prefix frontend run build
```

启动前端开发服务器后运行：

```powershell
node frontend/scripts/check-phase12-task12-material-library-layout.mjs http://127.0.0.1:5173
```

布局脚本必须拦截 9000/19000，覆盖 1280×800 与 375×667，检查私有/平台/回收站、网格/列表、详情、导入队列、移动抽屉，并断言无横向溢出、按钮遮挡、控制台错误和空白媒体区域。

- [ ] **Step 6: 提交**

```powershell
git add frontend/src/features/ai-edit/types.ts frontend/src/features/ai-edit/api.ts frontend/src/features/ai-edit/localApi.ts frontend/src/features/ai-edit/pages/MaterialLibrary.tsx frontend/src/pages/Index.tsx frontend/src/features/ai-edit/components/MaterialFilters.tsx frontend/src/features/ai-edit/components/MaterialGrid.tsx frontend/src/features/ai-edit/components/MaterialDetail.tsx frontend/src/features/ai-edit/components/MaterialTimeline.tsx frontend/src/features/ai-edit/components/ImportQueue.tsx frontend/scripts/check-phase12-task12-material-library-contract.mjs frontend/scripts/check-phase12-task12-material-library-layout.mjs
git commit -m "功能：重做 AI 素材库管理工作台"
```

---

## Task 12-9：本地/模拟闭环与检查点 C

**Files:**
- Create: `tests/test_phase12_task12_material_e2e.py`
- Create: `tests/test_phase12_task12_no_network.py`
- Create: `scripts/smoke_phase12_task12_material_synthetic.py`
- Modify: `docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`
- Modify: `docs/ai/05_PROJECT_CONTEXT.md`
- Modify: `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md`

- [ ] **Step 1: 写四边界端到端测试**

使用临时 SQLite、临时本机目录、临时云端目录、替身 9100 和真实 FastAPI TestClient，验证：导入去重 → 自动分析 → 五阶段回写 → 人工确认 → 云端上传 → 本地/云端预览 → 回收站 → 恢复 → 到期清理。另覆盖 9100 失败只影响内容分析、19000 重启恢复、旧 attempt 409 和跨商户 404。

- [ ] **Step 2: 写零网络哨兵**

```python
@pytest.fixture(autouse=True)
def forbid_external_network(monkeypatch):
    calls = []
    def blocked(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Task 12 测试禁止真实外部网络")
    monkeypatch.setattr("urllib.request.urlopen", blocked)
    monkeypatch.setattr("httpx.Client.request", blocked)
    monkeypatch.setattr("requests.sessions.Session.request", blocked)
    yield
    assert calls == []
```

测试中的内部 HTTP 必须用 TestClient/替身注入，不通过真实 socket。

- [ ] **Step 3: 合成媒体 smoke**

脚本用 FFmpeg 生成 3 秒带音频竖屏视频，执行 ffprobe、场景/关键帧/稳定性替身与云端临时目录上传。输出必须明确写“本地合成媒体 smoke”，不得声称真实模型或宝塔通过。

- [ ] **Step 4: 运行最终矩阵**

```powershell
python -m pytest tests/test_phase12_task12_material_schema.py tests/test_phase12_task12_material_api.py tests/test_phase12_task12_material_analysis.py tests/test_phase12_task12_material_semantic.py tests/test_phase12_task12_material_cloud.py tests/test_phase12_task12_material_preview.py tests/test_phase12_task12_material_lifecycle.py tests/test_phase12_task12_cleanup_scheduler.py tests/test_phase12_task12_material_e2e.py tests/test_phase12_task12_no_network.py -q
python -m pytest tests/test_phase12_ai_edit_schema.py tests/test_phase12_ai_edit_api.py tests/test_phase12_ai_edit_service.py tests/test_phase12_ai_edit_internal_api.py tests/test_phase12_ai_edit_pipeline.py tests/test_phase12_local_ai_edit_routes.py tests/test_phase12_local_ai_edit_supervisor.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py -q
python scripts/smoke_phase12_task12_material_synthetic.py
node frontend/scripts/check-phase12-task12-material-library-contract.mjs
npm --prefix frontend run build
```

Expected：Task 12 全套 0 failed；关联回归无新增失败；真实外部网络 0；真实宝塔 0；真实付费模型 0。

- [ ] **Step 5: 同轮更新当前事实**

只有上述证据通过后，原位更新专题、`05_PROJECT_CONTEXT.md` 和主计划。状态写为 `CHECKPOINT_C_BLOCKED`，不得提前写 `DONE_WITH_CONCERNS`；检查点 C 三方 PASS 后再原位改为 `TASK12_DONE_WITH_CONCERNS`，唯一生产 concern 仍为 `baota_ai_edit_production_not_verified`。

- [ ] **Step 6: 提交并硬暂停检查点 C**

```powershell
git add tests/test_phase12_task12_material_e2e.py tests/test_phase12_task12_no_network.py scripts/smoke_phase12_task12_material_synthetic.py docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md docs/ai/05_PROJECT_CONTEXT.md docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
git commit -m "测试：完成 Task 12 素材库本地闭环验收"
```

检查点 C 由规范、质量、安全三方复审：需求覆盖、真实链路、零伪状态、商户隔离、路径与日志脱敏、导航/标题/模块切换回归、桌面/移动截图。三方 PASS 前不得构建 EXE。

---

## Task 12-10：单入口测试 EXE 重建

**Files:**
- Modify: `requirements-ai-edit-worker.txt`
- Modify: `ai_edit_worker.spec`
- Modify: `scripts/build_phase12_single_test_exe.ps1`
- Modify: `scripts/smoke_phase12_task11_real.py`
- Create: `scripts/smoke_phase12_task12_material_exe.py`
- Modify: `docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md`
- Modify: `docs/ai/05_PROJECT_CONTEXT.md`

- [ ] **Step 1: 固定打包依赖与资源**

`requirements-ai-edit-worker.txt` 增加固定版本 `scenedetect==0.6.7.1`；Worker spec 显式收集 `funasr/cv2/scenedetect` 及 Task 12 新模块，仍排除 FastAPI/uvicorn。构建脚本在打包前导入检查依赖，验证 FFmpeg/ffprobe，并要求 `resources/funasr_models/configuration.json` 及至少一个 `.pt` 或 `.onnx` 模型文件存在；模型目录收集到包内 `models/funasr`。不得把 token、客户路径或数据库写入包，运行时设置 `AI_EDIT_ASR_MODEL_DIR` 为包内目录并禁止在线更新。

- [ ] **Step 2: 重建唯一测试 EXE**

```powershell
$Python310Exe = $env:PHASE12_PYTHON310_EXE
$Python311Exe = $env:PHASE12_PYTHON311_EXE
$FfmpegDir = $env:PHASE12_FFMPEG_DIR
if (-not (Test-Path $Python310Exe)) { throw "PHASE12_PYTHON310_EXE 无效" }
if (-not (Test-Path $Python311Exe)) { throw "PHASE12_PYTHON311_EXE 无效" }
if (-not (Test-Path (Join-Path $FfmpegDir 'ffmpeg.exe'))) { throw "PHASE12_FFMPEG_DIR 无效" }
powershell -ExecutionPolicy Bypass -File scripts/build_phase12_single_test_exe.ps1 `
  -Python310Exe $Python310Exe `
  -Python311Exe $Python311Exe `
  -FfmpegDir $FfmpegDir `
  -TestApiUrl https://merchant.xiaogaoai.cn/api `
  -TestFrontendUrl https://merchant.xiaogaoai.cn/ `
  -MerchantId m_nc_2bba00063cc13016
```

执行窗口必须在当前 PowerShell 会话设置三个环境变量；实际路径不得写入 Git。输出仍只有 `dist/phase12-task11/小高AI系统测试版.exe`，禁止产生第二个交付 EXE。

- [ ] **Step 3: 真实本机 EXE smoke**

启动 EXE 后验证：`/health` 200、19000 鉴权三态、AI 素材路由注册、导入合成媒体后自动分析收敛、本地预览 Range、临时云端目录上传、回收站恢复、Worker 进程退出和 19000 端口释放。不得连接真实宝塔或真实模型。

- [ ] **Step 4: 回归、哈希与文档**

```powershell
python -m pytest tests/test_phase12_task11_launcher.py tests/test_phase12_task12_material_e2e.py tests/test_phase12_local_ai_edit_routes.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py -q
Get-FileHash -Algorithm SHA256 -LiteralPath 'dist/phase12-task11/小高AI系统测试版.exe'
```

交付报告原位替换 EXE 大小、SHA、Task 12 smoke 结果和限制；旧 SHA 不得继续作为当前值保留。

- [ ] **Step 5: 提交源码与报告**

```powershell
git add requirements-ai-edit-worker.txt ai_edit_worker.spec scripts/build_phase12_single_test_exe.ps1 scripts/smoke_phase12_task11_real.py scripts/smoke_phase12_task12_material_exe.py docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md docs/ai/05_PROJECT_CONTEXT.md
git commit -m "交付：重建支持素材库闭环的测试 EXE"
```

`dist/` 与 `build/` 继续不提交。最终状态可写 `BUILT_FOR_CUSTOMER_TEST`，但宝塔生产验证仍为 `NOT_STARTED`。

---

## 2. 最终回传模板

```text
状态：检查点 C 后为 TASK12_DONE_WITH_CONCERNS；EXE smoke 后为 BUILT_FOR_CUSTOMER_TEST
提交链：按每个 Task 固定回传中记录的哈希顺序列出，仅包含 Task 12 提交
检查点：A PASS / B PASS / C PASS
测试矩阵：原样回传 Task 12 全套与关联回归命令输出
网络调用：真实外网 0；真实宝塔 0；真实付费模型 0
媒体调用：仅本机合成媒体 FFmpeg/ffprobe 与批准的 EXE smoke
前端：合同 PASS；构建 PASS；桌面/移动布局 PASS
EXE：路径、大小、SHA-256、19000 端口释放
文档影响：专题、05_PROJECT_CONTEXT、主计划已原位更新
残留 concern：baota_ai_edit_production_not_verified
硬暂停：不进入 Phase 13，不启动宝塔生产验证
```
