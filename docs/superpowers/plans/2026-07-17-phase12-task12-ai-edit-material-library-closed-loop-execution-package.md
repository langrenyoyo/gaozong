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

- Task 12-1 先完成合同红灯与历史重复盘点；仅在重复为 0 时才与 Task 12-2 连续执行，发现重复立即硬暂停 `Task 12-2-FIX-DATA`。Task 12-2 后硬暂停检查点 A。
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

### 1.5 施工复用矩阵

执行窗口先复用下列现有实现，禁止另起一套同职责代码：

| 能力 | 本仓库直接复用 | 外部项目只读参考 | 禁止复制 |
|---|---|---|---|
| 9000 素材归属、脱敏、软删 | `app/services/ai_edit_service.py` 的异常、`redact_sensitive_text`、商户隔离模式 | - | 新建第二套素材 service |
| 9000 路由鉴权 | `app/routers/ai_edit.py` 的 `_require_ai_edit/_merchant` 和 Local Agent token 依赖 | - | 前端自报 `merchant_id`、新权限码 |
| 19000 本地存储 | `app/local_agent_ai_edit_storage.py` 的安全段、原子清单、受管根 | - | 外部绝对路径、递归删除商户根 |
| 19000 子进程 | `app/local_agent_main.py` 的 `_ai_edit_executor` 与 `apps/ai_edit/media_tools.py` | - | 裸 `subprocess.run`、`shell=True`、新子进程启动器 |
| 增稳 | `apps/ai_edit/stabilizer.py` | BrollStudio 审计结论只用于核对参数 | 覆盖原素材、丢音频 |
| ASR | `apps/ai_edit/media_tools.py` 执行 FFmpeg 抽 WAV | `auto_edit/src/auto_edit/transcription.py::transcribe_wav_with_funasr_python_api`、`auto_edit/src/auto_edit/adapters/transcriber.py::parse_funasr_result` | FunASR 命令行、在线模型名、固定 1 秒兜底 |
| 场景与关键帧 | 本任务新建的可注入适配器 | `auto_edit/src/auto_edit/visual_analysis.py::_make_default_scene_detector/_make_default_frame_extractor` | `visual_report.json` 中的 `source_path`、YOLO/open_clip 重依赖默认启用 |
| 多模态消息 | `OpenAICompatibleClient.chat` 与现有 planner 严格解析/计费模式 | `auto_edit/docs/archive/reference/多模态模型能力和接口文档.md` 的图片消息格式 | Files API 整视频上传、外部项目密钥与客户端 |
| 前端外壳 | 当前真实 `MaterialLibrary.tsx` 的 header、`ModuleTabs`、颜色和 `Index.tsx` 路由分发 | 已批准视觉稿只参考内容区 | 修改全局导航、标题栏、模块切换 |
| 单入口 EXE | Task 11 的双运行时构建脚本、spec 与启动 smoke | - | 第二个交付 EXE、把 token 写入包 |

外部参考代码不能整文件复制。每个迁入函数必须删除绝对路径字段、样片词、原始 stdout/stderr、在线下载和外部仓库 import，并补本仓库合同测试。

### 1.6 固定接口矩阵

以下路径在 Task 12 内锁定，后续任务和前端不得自行改名：

| 边界 | 方法与路径 | 鉴权 | 用途 |
|---|---|---|---|
| 9000 商户 | `GET /ai-edit/materials` | 登录态 + `auto_wechat:ai_edit` | 筛选分页列表 |
| 9000 商户 | `GET /ai-edit/materials/{material_id}` | 同上 + 商户隔离 | 详情与有效分析 |
| 9000 商户 | `GET /ai-edit/materials/{material_id}/thumbnail` | 同上 | 安全缩略图 |
| 9000 商户 | `POST /ai-edit/materials/{material_id}/content-ticket` | 同上 | 签发 60 秒云端预览票据 |
| 9000 商户 | `GET /ai-edit/materials/content?ticket=...` | 短票据 | 云端 Range 预览 |
| 9000 商户 | `PATCH /ai-edit/materials/{material_id}/annotations` | 同上 | 人工确认，不改 AI 快照 |
| 9000 Local Agent | `POST /ai-edit/materials` | `X-Local-Agent-Token` | 注册并返回规范 ID、disposition、needs_analysis |
| 9000 Local Agent | `POST /ai-edit/materials/agent/{material_id}/processes/{stage}/claim` | `X-Local-Agent-Token` | expected_attempt CAS 领取阶段 attempt/令牌 |
| 9000 Local Agent | `PUT /ai-edit/materials/agent/{material_id}/processes/{stage}` | `X-Local-Agent-Token` + 阶段令牌 | attempt 条件状态回写 |
| 9000 Local Agent | `POST /ai-edit/materials/agent/{material_id}/analysis` | 同上 | 严格本地分析结果与缩略图登记 |
| 9000 Local Agent | `PUT /ai-edit/materials/agent/{material_id}/content` | 同上 | 原始请求体流式上传 |
| 9000 Local Agent | `POST /ai-edit/materials/agent/{material_id}/restore` | 同上 | 幂等恢复 |
| 9000 Local Agent | `POST /ai-edit/materials/agent/{material_id}/purge/prepare` | 同上 | 活动引用与删除状态预检 |
| 9000 Local Agent | `POST /ai-edit/materials/agent/{material_id}/purge/finalize` | 同上 | 幂等清云端并保留 tombstone |
| 9000 超管 | `GET /admin/ai-edit/materials` | 登录态 + `context.super_admin` + AI 剪辑能力 | 平台公共素材列表 |
| 9000 超管 | `POST /admin/ai-edit/materials/{material_id}/publish` | 同上 | 从已验证私有素材发布公共副本 |
| 9000 超管 | `PATCH /admin/ai-edit/materials/{material_id}` | 同上 | 编辑公共展示字段与人工标注 |
| 9000 超管 | `DELETE /admin/ai-edit/materials/{material_id}` | 同上 | 删除平台公共素材 |
| 19000 | `POST /agent/ai-edit/materials/{material_id}/analyze` | Local Agent token | 重新分析 |
| 19000 | `POST /agent/ai-edit/materials/{material_id}/upload` | 同上 | 主动上传云端 |
| 19000 | `POST /agent/ai-edit/materials/{material_id}/stabilize` | 同上 | 一键增稳生成衍生素材 |
| 19000 | `POST /agent/ai-edit/materials/{material_id}/restore` | 同上 | 跨端恢复协调 |
| 19000 | `DELETE /agent/ai-edit/materials/{material_id}/permanent` | 同上 | 跨端永久删除协调 |
| 19000 | `POST /agent/ai-edit/materials/{material_id}/preview-ticket` | 同上 | 签发 60 秒本地预览票据 |
| 19000 | `GET /agent/ai-edit/materials/preview?ticket=...` | 短票据 | `<video>` 多次 Range 预览 |
| 9100 | `POST /internal/ai-edit/materials/analyze` | 内部服务 token | 一次严格多模态分析 |

平台注册响应固定 `{material_id, disposition, needs_analysis}`，`disposition` 只允许 `created/existing/restored`。不同阶段使用独立 claim：19000 对需要执行的阶段调用 `/claim`，请求 `{source_sha256, expected_attempt}`，9000 CAS 推进并返回 `{stage, attempt_count, execution_token}`；原始令牌只返回本次一次，公共 DTO 和后续查询不返回。`existing` 注册不能恢复旧令牌，只能重新 claim。

平台公共素材一期不新增第二套本地鉴权：超管先按普通私有素材完成本机导入、分析和主动云端上传，再由 `/admin/ai-edit/materials/{material_id}/publish` 把已验证快照复制为 `scope=platform` 的云端公共素材。发布源必须是当前超管登录上下文可访问的私有素材；无绑定商户时拒绝发布，其他商户素材统一 404。平台 ID 固定为 `plat_` + `sha256(source_material_id + source_sha256 + "platform-v1")[:40]`，重复/并发发布返回同一公共记录；公共记录 `parent_material_id=source_material_id`，私有记录不变。发布必须复制到平台受管存储键，不能让公共记录继续引用商户私有存储键；编辑/删除接口只接受 `scope=platform`，重新分析走私有源后再发布新快照。

---

## Task 12-1：冻结合同与红灯

**Files:**
- Create: `tests/test_phase12_task12_material_schema.py`
- Create: `tests/test_phase12_task12_material_api.py`
- Create: `tests/test_phase12_task12_material_analysis.py`
- Create: `tests/test_phase12_task12_material_cloud.py`
- Create: `tests/test_phase12_task12_duplicate_audit.py`
- Create: `frontend/scripts/check-phase12-task12-material-library-contract.mjs`
- Create: `scripts/audit_phase12_task12_duplicate_materials.py`

- [ ] **Step 1: 冻结 ORM 与迁移红灯**

在 `test_phase12_task12_material_schema.py` 固定：

```python
EXPECTED_MATERIAL_COLUMNS = {
    "display_name", "description", "category", "duration_seconds",
    "width", "height", "fps", "file_size_bytes",
    "manual_override_json", "manual_confirmed_at",
    "purge_operation_id", "purge_status",
}
EXPECTED_STAGES = {
    "media_probe", "transcript", "content_analysis", "stability", "cloud_upload",
}
EXPECTED_MEDIA_TYPES = {"video", "audio", "image"}

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

另固定跨商户同哈希可并存、跨商户同临时 `material_id` 不冲突、规范 ID 由可信商户 + SHA 确定性生成、平台只读、视频/音频/图片三类、五阶段响应不含 `merchant_id/storage_key/absolute_path`。

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

重复盘点脚本不得导入 `app.database` 或读取 `DATABASE_URL/SMOKE_DATABASE_URL`。参数解析与目标校验按下面的纯函数落地，必须二选一显式传 `--database-url` 或 `--snapshot-mainline-sqlite`；SQLite URL 只接受已存在且不是仓库活动库 `data/auto_wechat.db` 的本地副本，PostgreSQL 只接受显式 `--allow-local-test-postgres`、回环主机和 `_test/_staging` 数据库：

```python
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import logging
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from migrations.migrate_sqlite import MAINLINE_DB, backup_database

ACTIVE_SQLITE = Path(MAINLINE_DB).resolve()
LOCAL_PG_HOSTS = {"127.0.0.1", "localhost", "::1"}

def parse_args(argv: list[str] | None = None):
    parser = ArgumentParser(description="只读盘点 Task 12 重复素材")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database-url")
    source.add_argument("--snapshot-mainline-sqlite", action="store_true")
    parser.add_argument("--allow-local-test-postgres", action="store_true")
    return parser.parse_args(argv)

def snapshot_sqlite(source: str, destination: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path != ACTIVE_SQLITE or not source_path.is_file():
        raise ValueError("只允许从仓库活动 SQLite 制作一致性副本")
    if destination_path == ACTIVE_SQLITE:
        raise ValueError("副本目标不得覆盖活动 SQLite")
    migration_logger = logging.getLogger("migrate_sqlite")
    was_disabled = migration_logger.disabled
    migration_logger.disabled = True
    try:
        backup_database(source_path, destination_path)
    finally:
        migration_logger.disabled = was_disabled
    return destination_path

def validate_database_target(raw: str, *, allow_local_test_postgres: bool) -> URL:
    url = make_url(raw)
    if url.drivername.startswith("sqlite"):
        if not url.database or url.database == ":memory:":
            raise ValueError("盘点必须使用已落盘的 SQLite 数据库副本")
        copy_path = Path(url.database).expanduser().resolve()
        if copy_path == ACTIVE_SQLITE:
            raise ValueError("禁止直接盘点仓库活动 SQLite，必须先制作副本")
        if not copy_path.is_file():
            raise ValueError("SQLite 数据库副本不存在")
        return url
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("只允许 SQLite 副本或本地测试 PostgreSQL")
    if not allow_local_test_postgres:
        raise ValueError("本地测试 PostgreSQL 必须显式批准")
    if (url.host or "").lower() not in LOCAL_PG_HOSTS:
        raise ValueError("拒绝非回环 PostgreSQL 主机")
    database = (url.database or "").lower()
    if not database.endswith(("_test", "_staging")):
        raise ValueError("PostgreSQL 数据库名必须以 _test 或 _staging 结尾")
    if url.query:
        raise ValueError("盘点 URL 禁止 query 参数")
    return url

DUPLICATE_SQL = text("""
    SELECT merchant_id, source_sha256, count(*) AS duplicate_count
    FROM ai_edit_materials
    WHERE merchant_id IS NOT NULL
    GROUP BY merchant_id, source_sha256
    HAVING count(*) > 1
    ORDER BY source_sha256
""")

def audit_duplicates(url: URL) -> list[dict[str, object]]:
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                if url.drivername.startswith("postgresql"):
                    conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                else:
                    conn.exec_driver_sql("PRAGMA query_only = ON")
                return [dict(row) for row in conn.execute(DUPLICATE_SQL).mappings()]
            finally:
                transaction.rollback()
    finally:
        engine.dispose()

def report_duplicates(database_url: str, *, allow_local_test_postgres: bool) -> int:
    url = validate_database_target(
        database_url,
        allow_local_test_postgres=allow_local_test_postgres,
    )
    rows = audit_duplicates(url)
    for row in rows:
        merchant_fingerprint = sha256(str(row["merchant_id"]).encode("utf-8")).hexdigest()[:12]
        source_fingerprint = str(row["source_sha256"])[:12]
        print(f"merchant={merchant_fingerprint} source={source_fingerprint} count={row['duplicate_count']}")
    print(f"duplicate_groups={len(rows)}")
    return 2 if rows else 0

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.snapshot_mainline_sqlite:
        with TemporaryDirectory(prefix="auto_wechat_task12_audit_") as temp_dir:
            copy_path = snapshot_sqlite(ACTIVE_SQLITE, Path(temp_dir) / "audit.db")
            return report_duplicates(
                f"sqlite+pysqlite:///{copy_path.as_posix()}",
                allow_local_test_postgres=False,
            )
    return report_duplicates(
        args.database_url,
        allow_local_test_postgres=args.allow_local_test_postgres,
    )
```

脚本复用 `migrations/migrate_sqlite.py::backup_database()` 的 SQLite backup API 制作活动库事务一致性快照，禁止 `Copy-Item` 主文件，因为 WAL 中未检查点的数据不会被普通文件复制捕获。`--snapshot-mainline-sqlite` 由脚本内部 `TemporaryDirectory` 生成随机目录并在成功、重复返回码或异常时统一清理，实际审计仍只连接副本；不得把副本路径打印到日志。PostgreSQL 在查询前执行 `SET TRANSACTION READ ONLY`，查询结束统一回滚并 `engine.dispose()`。输出只含重复组总数与 `sha256(merchant_id)[:12]`、`source_sha256[:12]`、计数，不回显 URL、用户名、密码、原 merchant ID。

`tests/test_phase12_task12_duplicate_audit.py` 至少固定：缺参数拒绝、活动 SQLite 作为 `--database-url` 拒绝、不存在副本拒绝、快照目标覆盖源拒绝、备份 helper 对已存在目标拒绝、远程 PG 拒绝、未显式批准 PG 拒绝、非测试库名拒绝、本地 `_test` PG 纯校验通过。另用临时 SQLite 开启 `PRAGMA journal_mode=WAL`，关闭自动 checkpoint，在另一个连接保持未提交读事务后插入同商户同 SHA 两行；monkeypatch 模块级 `ACTIVE_SQLITE` 指向临时源库，调用 `main(["--snapshot-mainline-sqlite"])`，断言返回重复码 2、输出 `duplicate_groups=1`，并用替身 `TemporaryDirectory` 记录路径后断言退出时目录已删除，证明 WAL 数据不漏且完整副本不残留。测试不得触碰仓库活动库。

```powershell
python -m pytest tests/test_phase12_task12_material_schema.py tests/test_phase12_task12_material_api.py tests/test_phase12_task12_material_analysis.py tests/test_phase12_task12_material_cloud.py -q
python -m pytest tests/test_phase12_task12_duplicate_audit.py -q
node frontend/scripts/check-phase12-task12-material-library-contract.mjs
python scripts/audit_phase12_task12_duplicate_materials.py --snapshot-mainline-sqlite
if ($LASTEXITCODE -ne 0) { throw 'Task 12 重复素材盘点失败' }
```

Expected：合同测试因 `AiEditMaterialProcess`、0034/0015、回收站查询、自动分析、云端存储和新组件缺失而失败；不得出现 fixture 导入错误。盘点脚本只连接上面显式创建的开发库副本，不读取环境数据库 URL；结果写入固定回传，非 0 时不提交“可继续 Task 12-2”的结论，立即硬暂停。若需盘点 PostgreSQL，操作者必须先显式设置当前 PowerShell 会话的 `$env:TASK12_AUDIT_DATABASE_URL`，再运行下面命令；脚本仍会拒绝非回环主机、非 `_test/_staging` 库和带 query 的 URL。本计划任何步骤都不连接生产或未知远程数据库。

```powershell
if (-not $env:TASK12_AUDIT_DATABASE_URL) { throw '缺少显式 TASK12_AUDIT_DATABASE_URL' }
python scripts/audit_phase12_task12_duplicate_materials.py --database-url $env:TASK12_AUDIT_DATABASE_URL --allow-local-test-postgres
if ($LASTEXITCODE -ne 0) { throw 'Task 12 PostgreSQL 测试副本重复素材盘点失败' }
```

```powershell
git add tests/test_phase12_task12_material_schema.py tests/test_phase12_task12_material_api.py tests/test_phase12_task12_material_analysis.py tests/test_phase12_task12_material_cloud.py tests/test_phase12_task12_duplicate_audit.py frontend/scripts/check-phase12-task12-material-library-contract.mjs scripts/audit_phase12_task12_duplicate_materials.py
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
    execution_token_hash = Column(String(64), nullable=False)
    failure_code = Column(String(64))
    error_summary = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
```

`AiEditMaterial.__table_args__` 追加以下两条约束，SQLite 0034 与 PostgreSQL 0015 使用完全相同的表达式和名称，禁止只在 service 校验：

```python
CheckConstraint(
    "purge_status IS NULL OR purge_status IN ('preparing','completed')",
    name="ck_ai_edit_materials_purge_status",
),
CheckConstraint(
    "(purge_status IS NULL AND purge_operation_id IS NULL) OR "
    "(purge_status IS NOT NULL AND purge_operation_id IS NOT NULL)",
    name="ck_ai_edit_materials_purge_pair",
),
```

迁移合同测试必须分别构造“空 status + 非空 operation”“非空 status + 空 operation”“未知 status”三类红灯，并静态断言 ORM、SQLite、PG 三方均存在两个约束名。

`AiEditMaterial` 增加规格中的 12 列，并增加 `(merchant_id, source_sha256)` 唯一约束。`AiEditMaterialOut` 只增加安全展示与媒体字段以及 `processes: list[AiEditMaterialProcessOut]`，不得暴露内部键、`purge_operation_id` 或 `execution_token_hash`。

12 列的类型按下列合同锁定，`file_size_bytes` 必须用 `BigInteger`，避免接近 2GB 的视频溢出 PostgreSQL `INTEGER`：

```python
display_name = Column(String(255))
description = Column(Text)
category = Column(String(32))
duration_seconds = Column(Float)
width = Column(Integer)
height = Column(Integer)
fps = Column(Float)
file_size_bytes = Column(BigInteger)
manual_override_json = Column(Text)
manual_confirmed_at = Column(DateTime)
purge_operation_id = Column(String(64))
purge_status = Column(String(16))
```

`manual_override_json` 仍由严格 Pydantic DTO 序列化，禁止 service 直接信任任意 JSON 字符串。沿用现有 `idx_ai_edit_materials_merchant_scope`、`idx_ai_edit_materials_sha256`，新增唯一约束即可；`ai_edit_material_processes` 的唯一约束已覆盖按素材/源版本/阶段回查，本任务不堆叠重复索引。

公共 schema 分离列表与详情：`AiEditMaterialOut` 只放卡片摘要和五阶段；`AiEditMaterialDetailOut` 才放当前有效分析、人工覆盖和时间轴。人工写入固定使用下面的严格请求，不允许客户端覆盖 AI 快照、SHA、scope 或内部存储字段：

```python
class MaterialRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., gt=0)

class AiEditMaterialAnnotationsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=2000)
    category: Literal["spoken", "broll", "highlight", "uncategorized"] | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    usable_ranges: list[MaterialRange] | None = Field(default=None, max_length=100)
```

service 在已读取 `duration_seconds` 后统一验证每个区间 `0 <= start < end <= duration`，标签逐项 strip、拒绝空值并限制 64 字符，再以规范 JSON 写入 `manual_override_json` 和 `manual_confirmed_at`。

Task 12-1 在迁移红灯前先对临时 SQLite 副本和只读 PG 测试 fixture 执行重复盘点：

```sql
SELECT merchant_id, source_sha256, count(*)
FROM ai_edit_materials
WHERE merchant_id IS NOT NULL
GROUP BY merchant_id, source_sha256
HAVING count(*) > 1;
```

`scripts/audit_phase12_task12_duplicate_materials.py` 使用 Task 12-1 冻结的独立只读 engine，不导入 `app.database`，不读取任何环境数据库 URL。它输出总重复组数与脱敏的 `sha256(merchant_id)[:12] + source_sha256[:12] + count`，不打印原 merchant ID；PG 本地测试环境复用同一 SQLAlchemy 查询。若任何副本返回重复，Task 12-2 不得开始，硬暂停并单开 `Task 12-2-FIX-DATA`：先固定规范行选择、`ai_edit_job_materials` 引用迁移、分析快照归属、本地清单协调与逐行审计，再经数据库 Reviewer 批准；0034/0015 永不静默删除或合并历史行。无重复时把查询结果 0 行作为检查点 A 证据。

- [ ] **Step 2: 写 SQLite 0034 升降级**

升级脚本在任何 `RENAME` 前执行。下面只展示关键 guard 形态，实际 0034 必须完整复制 0033 的 `pragma_table_xinfo` 精确列集、双向 `EXCEPT`、索引重建和事务骨架，不得把此片段当完整迁移脚本：

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

使用 `pragma_table_xinfo` 固定 0033 的 `ai_edit_materials` 17 个普通列和无隐藏列；同时固定 `ai_edit_material_analyses` 当前 9 个普通列不变，防实现窗口为了 description/category/highlights 擅自扩快照表。重建 `ai_edit_materials` 时逐列复制旧数据，12 个新列保持 `NULL`。用包含 `id`、时间字段和全部旧业务列的双向 `EXCEPT` 与行数守卫证明无损。创建 `ai_edit_material_processes`、索引和版本登记。

降级只在 head 精确为 `0034` 时执行，拒绝未知列、隐藏列和后续版本；在任何 `DROP/RENAME` 前用 guard 查询 `purge_status IS NOT NULL`，存在 preparing 或 completed 都让 CHECK 失败并整体回滚，防丢失删除 claim 与 finalize 重放能力。迁移测试分别构造 preparing/completed，验证结构、数据、0034 登记和中间表状态原样保留。通过后恢复 0033 的 17 列并保留全部旧数据，`ai_edit_material_analyses` 始终保持 0032 建立的 9 列不变。

- [ ] **Step 3: 写 PostgreSQL 0015**

```python
revision = "0015_ai_edit_material_library"
down_revision = "0014_compute_usage_measurement"
```

`upgrade()` 只 `add_column/create_table/create_index/create_unique_constraint/create_check_constraint`，不 `create_all`。两个 purge CHECK 必须由 `op.create_check_constraint` 显式创建，不能依赖 ORM。`downgrade()` 只删除 0015 自身对象。历史重复 `(merchant_id, source_sha256)` 用前置 SQL 检查抛错，不删除或合并历史行。PG `downgrade()` 在删 claim 字段前执行下面的只读 guard；preparing/completed 任一存在都抛错，与 SQLite 降级保护一致：

```python
bind = op.get_bind()
claim_exists = bind.execute(sa.text(
    "SELECT 1 FROM ai_edit_materials WHERE purge_status IS NOT NULL LIMIT 1"
)).first()
if claim_exists is not None:
    raise RuntimeError("存在永久删除 claim 或 completed tombstone，拒绝降级 0015")
```

PostgreSQL 迁移测试分别构造 preparing/completed，证明两者均在任何对象删除前拒绝且事务无变化；静态合同测试断言 guard 位于任何 `drop_constraint/drop_column` 之前。

PG 参考代码只展示 revision 链，完整实现必须逐项写 12 个 `op.add_column`、`ai_edit_material_processes` 表（含 `execution_token_hash`）、唯一约束和必要索引；不能把 `revision/down_revision` 两行当完整 Alembic 文件。所有对象名与 ORM/SQLite 完全一致，静态合同测试逐个枚举。

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

增加精确测试：活跃/回收站互斥、页码与总数、关键词/分类/阶段筛选、跨商户 404、平台只读、非超管访问 `/admin/ai-edit/materials` 得 403、同商户 SHA 并发冲突恢复、公共响应键集脱敏。额外构造同一素材旧/新两个 `source_sha256` 的分析和阶段行，证明搜索、详情与筛选只使用当前 SHA；构造真实唯一约束冲突，证明 SAVEPOINT 后仍可回查且顶层事务可提交。

- [ ] **Step 2: 实现列表与规范 ID 去重**

服务签名固定为：

```python
def list_materials(db: Session, *, merchant_id: str, scope: str,
                   lifecycle: str, query: str | None, category: str | None,
                   tag: str | None, min_duration: float | None,
                   max_duration: float | None, created_from: datetime | None,
                   created_to: datetime | None, sort: str,
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
    elif lifecycle != "active":
        raise AiEditStatusConflict("PLATFORM_LIFECYCLE_READ_ONLY")
    if query or tag:
        latest_analysis_id = (
            db.query(func.max(AiEditMaterialAnalysis.id))
            .filter(
                AiEditMaterialAnalysis.material_id == AiEditMaterial.material_id,
                AiEditMaterialAnalysis.source_sha256 == AiEditMaterial.source_sha256,
            )
            .correlate(AiEditMaterial)
            .scalar_subquery()
        )
        q = q.outerjoin(
            AiEditMaterialAnalysis,
            AiEditMaterialAnalysis.id == latest_analysis_id,
        )
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        q = q.filter(or_(AiEditMaterial.display_name.ilike(like, escape="\\"),
                         AiEditMaterial.description.ilike(like, escape="\\"),
                         AiEditMaterialAnalysis.transcript_json.ilike(like, escape="\\")))
    if category:
        q = q.filter(AiEditMaterial.category == category)
    if tag:
        tag_token = json.dumps(tag, ensure_ascii=False)
        tag_token = tag_token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.filter(or_(
            AiEditMaterialAnalysis.tags_json.ilike(f"%{tag_token}%", escape="\\"),
            AiEditMaterial.manual_override_json.ilike(f"%{tag_token}%", escape="\\"),
        ))
    if min_duration is not None:
        q = q.filter(AiEditMaterial.duration_seconds >= min_duration)
    if max_duration is not None:
        q = q.filter(AiEditMaterial.duration_seconds <= max_duration)
    if created_from is not None:
        q = q.filter(AiEditMaterial.created_at >= created_from)
    if created_to is not None:
        q = q.filter(AiEditMaterial.created_at <= created_to)
    if stage or process_status:
        process_query = db.query(AiEditMaterialProcess.id).filter(
            AiEditMaterialProcess.material_id == AiEditMaterial.material_id,
            AiEditMaterialProcess.source_sha256 == AiEditMaterial.source_sha256,
        )
        if stage:
            process_query = process_query.filter(AiEditMaterialProcess.stage == stage)
        if process_status:
            process_query = process_query.filter(
                AiEditMaterialProcess.status == process_status
            )
        q = q.filter(process_query.exists())
    order_by = {
        "created_desc": (AiEditMaterial.created_at.desc(), AiEditMaterial.id.desc()),
        "created_asc": (AiEditMaterial.created_at.asc(), AiEditMaterial.id.asc()),
        "duration_desc": (AiEditMaterial.duration_seconds.desc(), AiEditMaterial.id.desc()),
        "duration_asc": (AiEditMaterial.duration_seconds.asc(), AiEditMaterial.id.asc()),
    }[sort]
    total = q.count()
    rows = q.order_by(*order_by).offset((page - 1) * page_size).limit(page_size).all()
    return total, rows
```

上面是查询核心，不是完整 service 文件；实现时使用当前模块已有 import、异常和 DTO 组装，不复制第二份 helper。普通商户接口的 `scope=platform` 只允许 `lifecycle=active`，平台回收记录只通过超管接口查看。`sort`、分页上下界和 `scope/lifecycle` 枚举先由路由 Pydantic/`Query` 校验，再进入该函数。

标签筛选只匹配最新分析快照的规范 JSON 标签值和人工覆盖标签；时长、创建时间与排序在数据库查询阶段完成，禁止先分页再用 Python 过滤。为 `scope/lifecycle/category/stage/status/min_duration/max_duration/created_from/created_to/sort` 各写至少一个合同断言。

相关查询必须只连接 `AiEditMaterial.source_sha256` 对应的当前阶段与当前分析快照；禁止旧源版本的成功状态或转写参与搜索、详情和筛选。排序字段使用服务端白名单字典映射 SQLAlchemy 列，禁止把请求中的 `sort` 拼接成 SQL。

`register_material` 先按 `(merchant_id, source_sha256)` 回查全部历史行：活动行直接返回规范 ID；回收站或 `purge_after=NULL` 的已清理 tombstone 使用同一规范 ID 复活并清除删除字段；不得插入第二行。并发首次写入必须用 SAVEPOINT 捕获唯一约束冲突，不能在失败事务里直接回查：

```python
def _find_canonical_material(db, merchant_id: str, source_sha256: str):
    return db.query(AiEditMaterial).filter_by(
        merchant_id=merchant_id,
        source_sha256=source_sha256,
    ).one_or_none()

def _canonical_material_id(merchant_id: str, source_sha256: str) -> str:
    digest = hashlib.sha256(
        f"{merchant_id}:{source_sha256}".encode("utf-8")
    ).hexdigest()
    return f"mat_{digest[:40]}"

canonical = _find_canonical_material(db, merchant_id, source_sha256)
if canonical is None:
    try:
        with db.begin_nested():
            candidate = AiEditMaterial(
                material_id=_canonical_material_id(merchant_id, source_sha256),
                merchant_id=merchant_id,
                scope="merchant",
                media_type=media_type,
                storage_mode="local_only",
                agent_client_id=agent_client_id,
                source_sha256=source_sha256,
                parent_material_id=parent_material_id,
                analysis_status="pending",
                stabilization_status="pending",
            )
            db.add(candidate)
            db.flush()
        canonical = candidate
    except IntegrityError:
        canonical = _find_canonical_material(db, merchant_id, source_sha256)
        if canonical is None:
            raise
if canonical.purge_status == "preparing":
    raise AiEditStatusConflict("MATERIAL_PURGE_IN_PROGRESS")
if canonical.purge_status == "completed":
    if canonical.deleted_at is None:
        raise AiEditStatusConflict("MATERIAL_PURGE_STATE_INVALID")
    canonical.purge_status = None
    canonical.purge_operation_id = None
if canonical.deleted_at is not None:
    canonical.deleted_at = None
    canonical.purge_after = None
db.flush()
return canonical
```

路由仍只在顶层成功路径执行一次 `db.commit()`。复活 completed tombstone 时，删除字段与 `purge_status/purge_operation_id` 必须在同一事务清空；finalize 路由先要求素材仍为已删除 tombstone 且 claim 为 `preparing/completed`，因此旧 operation 在复活后只能返回中性冲突，绝不能删除新导入的本地或云端内容。补“completed 复活清 claim + 旧 finalize 冲突 + 新内容不变”端到端测试。请求中的 `material_id` 只作为本次浏览器临时关联 ID，不写数据库、不进日志；新素材统一使用可信商户 + 源 SHA 生成的规范 ID，保证跨商户同名/同文件可并存，同商户并发同文件必然收敛到同一 ID。9000 响应中的 `material_id` 是规范 ID，19000 不得继续使用客户端临时 ID。

Local Agent 可信注册请求允许可选 `parent_material_id`，仅用于增稳衍生素材；服务必须验证父素材属于同一商户且未删除，普通商户注册接口不得自报该字段。

- [ ] **Step 3: 实现阶段状态、分析快照和人工确认**

```python
def update_material_process(db, *, material, stage, status, progress,
                            attempt_count, execution_token,
                            failure_code=None, error_summary=None):
    row = db.query(AiEditMaterialProcess).filter_by(
        material_id=material.material_id,
        source_sha256=material.source_sha256,
        stage=stage,
    ).one_or_none()
    if row is None or attempt_count != row.attempt_count:
        raise AiEditStatusConflict("STALE_MATERIAL_ATTEMPT")
    incoming_token_hash = hashlib.sha256(execution_token.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(row.execution_token_hash, incoming_token_hash):
        raise AiEditStatusConflict("STALE_MATERIAL_ATTEMPT")
    normalized_error = redact_sensitive_text(error_summary)
    current = (row.status, row.progress, row.failure_code, row.error_summary)
    incoming = (status, progress, failure_code, normalized_error)
    if row.status in {"succeeded", "failed", "not_required"}:
        if current == incoming:
            return row
        raise AiEditStatusConflict("MATERIAL_STAGE_TERMINAL")
    allowed = {"queued": {"running", "failed"}, "running": {"running", "succeeded", "failed"}}
    if status not in allowed[row.status]:
        raise AiEditStatusConflict("MATERIAL_STAGE_TRANSITION_INVALID")
    row.status, row.progress, row.attempt_count = status, progress, attempt_count
    row.failure_code = failure_code
    row.error_summary = normalized_error
    row.completed_at = datetime.now() if status in {"succeeded", "failed", "not_required"} else None
    db.flush()
    return row
```

阶段行由 9000 注册素材时一次性创建，不在回写路径“先查后插”。重新分析用 SAVEPOINT/CAS 把当前非 running 阶段推进为 `attempt_count + 1, status=queued` 并生成 `secrets.token_hex(32)` 的新原始执行令牌，只把原始令牌下发 19000，数据库 `execution_token_hash` 只存 SHA-256。完整实现还必须校验 stage/status 枚举、状态与 progress 组合、商户归属和当前 SHA。双 Session 测试覆盖同时重新分析只有一个 claim 成功、attempt 跳号拒绝、同 attempt 同载荷幂等、不同载荷冲突、终态不可逆。

阶段初值按媒体类型固定，禁止让不适用阶段永久排队：

| 媒体类型 | `media_probe` | `transcript` | `content_analysis` | `stability` | `cloud_upload` |
|---|---|---|---|---|---|
| video | queued | queued | queued | queued | not_required |
| audio | queued | queued | queued | not_required | not_required |
| image | queued | not_required | queued | not_required | not_required |

用户主动上传时才把 `cloud_upload` 推进到 queued/running；禁止用旧的 `analysis_status=pending` 推断每个阶段。`status/progress` 组合必须校验：succeeded 固定 100，queued 固定 0，running 为 0..99，failed 保留最后进度，not_required 固定 0。

分析 JSON 先经 Pydantic 严格模型校验再写 `AiEditMaterialAnalysis`。按已批准的数据合同不再扩 `ai_edit_material_analyses`：转写写 `transcript_json`，场景与场景摘要写 `scenes_json`，AI 标签写 `tags_json`，高光作为 `kind="highlight"` 的时间区间与普通可用区间一起写 `usable_ranges_json`；当前 AI `description/category` 写 `ai_edit_materials.description/category`。详情组装按 `manual_override_json > 当前 AI description/category + 最新分析快照 > 空值` 合并，重新分析可更新当前 AI 基线但不得修改人工字段。测试固定旧快照不可变、最新当前 SHA 快照生效、人工覆盖仍优先。

- [ ] **Step 4: 实现商户与超管路由**

商户路由严格按 §1.6 固定矩阵实现。`admin_ai_edit.py` 复用 `get_request_context_required`，先要求 `context.super_admin`，再复用 AI 剪辑能力边界；普通商户统一 403。Task 12-3 先实现平台列表、编辑、删除和 `validate_platform_publish_source` 纯数据库预检；`publish` 的云端对象复制与公开提交必须等 Task 12-6 存储能力完成后在同一 admin router 中接通，不能在 Task 12-3 伪造云端成功。

`GET /ai-edit/materials` 使用显式 `Query` 参数；增加详情、缩略图、人工确认和 Local Agent 阶段/分析写入接口。新建 `admin_ai_edit.py`，固定前缀 `/admin/ai-edit`，仅 `context.super_admin` 可维护平台公共素材；`app/main.py` 只注册该路由，不改其他路由顺序或生命周期。不新增权限码。Task 12-3 的测试只冻结 publish 预检与鉴权，真实复制成功测试归 Task 12-6。

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
- Modify: `tests/test_phase12_local_ai_edit_storage.py`
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
    media_type: Literal["video", "audio", "image"]
    attempt_count: int = Field(..., ge=0)
    task_root: Path
    relative_path: str
    source_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    output_relative_path: str | None = None

    @model_validator(mode="after")
    def validate_operation_output(self):
        if self.operation == "stabilize" and self.media_type != "video":
            raise ValueError("只有视频素材允许增稳")
        if self.operation == "stabilize" and not self.output_relative_path:
            raise ValueError("增稳操作必须提供受管输出相对路径")
        return self

@dataclass
class MaterialAnalysisDeps:
    probe: Callable[[Path], dict]
    transcribe: Callable[[Path, float, Path], list[dict]]
    split_scenes: Callable[[Path, float], list[dict]]
    extract_keyframe: Callable[[Path, float, Path], None]
    measure_stability: Callable[[Path], dict]
```

这是合同骨架；执行窗口应把它并入现有 `apps/ai_edit/contracts.py`，复用 `_validate_relative_path` 校验 `relative_path/output_relative_path`，并给 `task_root` 与现有 Worker 相同的受信根二次解析，不另造宽松路径校验。

`run_material_analysis` 逐阶段调用依赖并写原子 `material-result.json`。视频执行 probe、ASR、场景、关键帧和稳定性；音频执行 probe、ASR，并以无关键帧文本请求做内容分析；图片执行 probe，把原图缩放为最大边 720px 的单关键帧后做内容分析。转写输出 WAV 和关键帧全部写入本次操作 `task_root/analysis/`，不写源素材目录。视频关键帧每场景 1 张、总数最多 12；场景超过 12 时按首尾覆盖的等距索引确定性抽样。迁入 `auto_edit` 时只复制解析/适配器逻辑，移除 `source_path` 和原始 stdout/stderr。

`MaterialRecord` 与 `materials.json` 必须新增 `media_type`、`suffix` 和安全展示名；`relative_path` 使用 `materials/{material_id}/source.{suffix}`，不再写无后缀的 `source`。旧清单缺这些字段时只允许通过受管文件探测一次后原子回写，探测失败标记不可用，不按 material ID 猜扩展名。导入先以随机临时名落盘并按真实内容探测：视频/音频用 ffprobe 流类型，图片用 OpenCV/Pillow 解码；浏览器 MIME 和文件名只用于展示，不作为可信媒体类型。

这是当前本地清单的兼容迁移，不新增本地 SQLite。升级函数必须使用新的严格读取器，不得复用当前损坏 JSON 时返回空清单的 `_load_manifest()`；JSON、字段或重复 ID 错误立即停止且不写文件。先备份 `materials.json`，全部记录探测成功后一次原子替换，任一失败保留旧清单和原文件。相邻回归必须证明 Task 11 已导入的无后缀 `source` 视频可迁移为 `source.mp4`，活动引用仍指向同一 `material_id`，损坏清单不会被覆盖为空。

生产依赖不得调用未保证存在的 `funasr` 或 `scenedetect` 命令：

```python
def normalize_funasr_segments(raw: object, duration: float) -> list[dict]:
    item = raw[0] if isinstance(raw, list) and raw else raw
    item = item if isinstance(item, dict) else {}
    sentences = item.get("sentence_info")
    if isinstance(sentences, list) and sentences:
        return [
            {
                "start_seconds": round(float(row["start"]) / 1000, 3),
                "end_seconds": round(float(row["end"]) / 1000, 3),
                "text": str(row.get("text") or "").strip(),
            }
            for row in sentences
            if str(row.get("text") or "").strip()
        ]
    text = str(item.get("text") or "").strip()
    return [{"start_seconds": 0.0, "end_seconds": duration, "text": text}] if text else []

def build_local_transcriber(model_dir: Path, *, ffmpeg_binary: str,
                            runner, cancel_check):
    if not model_dir.is_dir() or not (model_dir / "configuration.json").is_file():
        raise MaterialAnalysisError("ASR_MODEL_NOT_AVAILABLE")
    from funasr import AutoModel
    model = AutoModel(model=str(model_dir), device="cpu", disable_update=True)

    def transcribe(video_path: Path, duration: float, audio_path: Path) -> list[dict]:
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        runner(
            [ffmpeg_binary, "-y", "-i", str(video_path), "-vn",
             "-ac", "1", "-ar", "16000", str(audio_path)],
            timeout_seconds=300,
            cancel_check=cancel_check,
            cwd=audio_path.parent,
        )
        raw = model.generate(
            input=str(audio_path),
            batch_size_s=300,
            sentence_timestamp=True,
        )
        return normalize_funasr_segments(raw, duration)
    return transcribe

def split_scenes_with_pyscenedetect(video_path: Path, duration: float) -> list[dict]:
    from scenedetect import ContentDetector, SceneManager, open_video
    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector())
    manager.detect_scenes(video)
    scenes = [
        {"start": start.get_seconds(), "end": end.get_seconds()}
        for start, end in manager.get_scene_list()
    ]
    return scenes or [{"start": 0.0, "end": duration}]
```

以上归一逻辑从 `auto_edit` 的 `parse_funasr_result` 最小迁入，但主链路无句级时间戳时必须使用真实媒体时长，禁止其测试用 1 秒兜底。关键帧提取复用 `run_media_command`，滤镜固定为 `scale=720:720:force_original_aspect_ratio=decrease`。`AI_EDIT_ASR_MODEL_DIR` 只能指向随包本地目录，`disable_update=True` 且网络哨兵必须证明不下载模型。ASR 失败只把 transcript 阶段标记失败；场景、关键帧和稳定性继续执行。

- [ ] **Step 3: 实现独立持久化监督器**

`MaterialOperationSupervisor` 使用 `(merchant_id, material_id, operation)` 复合键，状态文件存受管相对清单路径、`stage_claims`、`pending_writeback` 和状态；文件权限沿用本机受管目录，不进入响应/日志。凭证结构固定为：

```python
class PersistedStageClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_count: int = Field(..., ge=0)
    execution_token: str = Field(..., min_length=64, max_length=64)

class PersistedMaterialOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant_id: str
    material_id: str
    operation: Literal["analyze", "stabilize", "cloud_upload"]
    manifest_relative_path: str
    stage_claims: dict[MaterialProcessStage, PersistedStageClaim]
    pending_writeback: list[MaterialProcessStage]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
```

各阶段 attempt 可以不同，禁止把它们压成单值。原始令牌只由 19000 Supervisor 状态文件持有，**不得写入 Worker manifest、argv、Worker 环境或 result**；Worker 结果只带各阶段结果，Supervisor 按 stage 从 `stage_claims` 取对应 attempt/令牌回写。`enqueue()` 在锁内接受 9000 下发的完整 `stage_claims`、原子持久化后入队；`recover()` 对 queued/running 使用同一映射重跑，不自行推进 9000 attempt，终态且 `pending_writeback` 非空的记录只逐阶段补回写、不重复媒体处理；`writeback(stage)` 必须携带该阶段令牌并拒绝旧 attempt。状态机只允许 `queued -> running -> succeeded/failed/cancelled`，重新分析先逐阶段向 9000 claim 新 attempt，不把旧终态直接改回 running。

测试必须构造 `media_probe.attempt_count=1`、`transcript.attempt_count=3`、`stability.attempt_count=2`，重启恢复后断言三次回写各自携带正确 attempt/令牌；再扫描 Worker manifest、子进程 argv/env、result 和日志，断言三个原始令牌均不存在。

- [ ] **Step 4: 接入导入链路和生产 Worker**

19000 导入完成并成功同步 9000 后，必须读取 9000 响应中的规范 `material_id`、`disposition` 和 `needs_analysis`。若规范 ID 与客户端临时 ID 不同，调用本地 `adopt_canonical_material_id`：本机已有同 SHA 的规范记录时删除本次重复受管副本并恢复规范记录；本机没有时把本次受管文件原子迁移到规范 ID；规范 ID 已存在但 SHA 不同则稳定失败，禁止排队。最终响应、清单和分析队列统一使用规范 ID，并原样返回 `disposition`；只有 `existing/restored` 显示为既有素材，首次 `created` 即使 ID 改变也显示导入成功。若 `needs_analysis=true`，19000 按媒体类型对每个可执行阶段调用 `/claim`，将返回的阶段令牌映射持久化到 Supervisor 后排队。增加“双文件同 SHA 只留下一个本机清单与一个受管文件”的测试。

规范 ID 对齐完成后立即创建 `operation=analyze` 清单并 `enqueue`。导入接口继续严格顺序处理文件，避免并发读改写 `materials.json`；分析和上传队列可独立并发。

`worker_main.main()` 必须先 `json.loads` 原始清单并读取 `schema_version`，再分派 Pydantic 模型：`phase12_ai_edit_worker_v1 -> WorkerManifest/run_pipeline/result.json`，`phase12_material_operation_v1 -> MaterialOperationManifest/run_material_analysis/material-result.json`；未知版本稳定失败，不能先用旧 `WorkerManifest` 解析。补两个 CLI 双回归。

现有 `_ai_edit_executor` 是嵌套且硬编码剪辑 supervisor，不能直接复用。Task 12-4 从 `local_agent_main.py` 提取一个共享 `_run_ai_edit_worker_process(job, *, register_process, result_name)`，仅封装参数数组、独立进程组、管道有界读取、超时与凭据环境剥离；剪辑 supervisor 和素材 supervisor 分别传自己的登记回调与结果文件名，不另写第二套 Popen 逻辑。终态回调逐阶段写回 9000，网络失败保留 `pending_writeback`，重启补偿。Task 12-4 结束时只允许本地 `media_probe/transcript/stability` 收敛，`content_analysis` 保持 queued；Task 12-5 接通 9100 后才可写 succeeded/failed，禁止提前伪绿。

现有导入必须调整为“本机临时文件 → ffprobe/图片解码校验 → 9000 注册得到规范 ID → 原子落入规范受管目录 → 清单 → 必要阶段 claim 与分析排队”。若 9000 注册失败，删除本次临时文件，不留下未登记素材；若规范落盘失败，保留稳定错误并允许同一文件重试，禁止用旧的“本机先成功、元数据 502”作为 Task 12 最终语义。`MaterialRegisterRequest.media_type` 必须由 19000 根据真实探测结果填写，不能信文件扩展名或浏览器 MIME。

Local Agent 启动时在素材 supervisor `start()` 前执行一次历史协调：严格读取本地清单，逐项按真实 SHA/媒体类型调用 9000 注册并采用规范 ID；若响应 `needs_analysis=true`，领取阶段 claim 后排队；若当前 SHA 已有完整分析快照则不重复分析。单项失败记录 `stage=material_startup_reconcile/failure_stage` 并继续下一项，不把旧 `analysis_status=pending` 当作已在处理中。测试覆盖 Task 11 历史无阶段行素材升级后最终收敛。

一键增稳创建 `operation=stabilize` 清单，调用现有 `apps.ai_edit.stabilizer.stabilize`，先输出到随机临时受管路径。完成后再次校验原素材 SHA-256 未变化、衍生文件可被 ffprobe 读取并计算衍生 SHA，再以临时 ID 和可信 `parent_material_id` 注册 9000；最终只采用 9000 返回的规范 ID 和 `adopt_canonical_material_id` 原子迁移结果。重复点击由衍生内容 SHA 去重并返回同一规范记录。失败时删除本次临时文件，不修改原素材与父素材记录。

- [ ] **Step 5: 运行并提交**

```powershell
python -m pytest tests/test_phase12_task12_material_analysis.py tests/test_phase12_local_material_supervisor.py tests/test_phase12_ai_edit_worker_contract.py tests/test_phase12_ai_edit_stabilizer.py tests/test_phase12_local_ai_edit_storage.py tests/test_phase12_local_ai_edit_routes.py tests/test_phase12_local_ai_edit_supervisor.py -q
git add apps/ai_edit/contracts.py apps/ai_edit/material_analysis.py apps/ai_edit/worker_main.py app/local_agent_ai_edit_material_supervisor.py app/local_agent_ai_edit_storage.py app/local_agent_ai_edit_routes.py app/local_agent_main.py tests/test_phase12_task12_material_analysis.py tests/test_phase12_local_ai_edit_storage.py tests/test_phase12_local_material_supervisor.py
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
- Modify: `apps/xg_douyin_ai_cs/llm/client.py`
- Modify: `app/schemas.py`
- Modify: `app/routers/ai_edit.py`
- Modify: `app/services/xg_douyin_ai_cs_client.py`
- Modify: `app/services/ai_edit_service.py`
- Create: `tests/test_phase12_task12_material_semantic.py`
- Modify: `tests/test_phase12_task12_material_api.py`
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

    @model_validator(mode="after")
    def validate_frame_bytes(self):
        try:
            decoded = base64.b64decode(self.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("关键帧不是合法 base64") from exc
        if len(decoded) > 512 * 1024:
            raise ValueError("关键帧解码后不得超过 512KB")
        is_jpeg = decoded.startswith(b"\xff\xd8\xff")
        is_webp = decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP"
        if self.mime_type == "image/jpeg" and not is_jpeg:
            raise ValueError("关键帧内容与 JPEG MIME 不匹配")
        if self.mime_type == "image/webp" and not is_webp:
            raise ValueError("关键帧内容与 WEBP MIME 不匹配")
        return self

class MaterialSemanticAnalysisRequest(BaseModel):
    model_config = {"extra": "forbid"}
    merchant_id: str = Field(..., min_length=1, max_length=128)
    material_id: str = Field(..., min_length=1, max_length=64)
    media_type: Literal["video", "audio", "image"]
    duration_seconds: float | None = Field(default=None, gt=0)
    transcript: list[TranscriptSegment] = Field(default_factory=list, max_length=100)
    scenes: list[SceneSummary] = Field(default_factory=list, max_length=100)
    keyframes: list[MaterialKeyframe] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_timeline(self):
        if self.media_type in {"video", "audio"} and self.duration_seconds is None:
            raise ValueError("视频和音频必须提供真实时长")
        if self.media_type == "video" and (not self.scenes or not self.keyframes):
            raise ValueError("视频必须提供场景与关键帧")
        if self.media_type == "audio" and not self.transcript:
            raise ValueError("音频必须提供转写")
        if self.media_type == "image" and (self.transcript or self.scenes or len(self.keyframes) != 1):
            raise ValueError("图片只允许一张受控关键帧")
        intervals = [*self.transcript, *self.scenes]
        if any(item.material_id != self.material_id for item in intervals):
            raise ValueError("分析片段只能引用当前素材")
        if self.duration_seconds is not None and any(
            not (0 <= item.start_seconds < item.end_seconds <= self.duration_seconds)
            for item in intervals
        ):
            raise ValueError("分析片段区间必须位于素材时长内")
        if self.duration_seconds is not None and any(
            frame.at_seconds > self.duration_seconds for frame in self.keyframes
        ):
            raise ValueError("关键帧时间不得超过素材时长")
        return self
```

这是新增 schema 的核心字段；`TranscriptSegment/SceneSummary` 复用现有定义并补当前素材/时长交叉校验，不创建同名第二套模型。

校验器按 `mime_type` 精确匹配魔数：JPEG 只接受 `FF D8 FF`，WEBP 只接受 `RIFF....WEBP`，不能只信客户端声明；为两种 MIME 不匹配各写红灯。

响应固定 `description/category/tags/highlights/usable_ranges/confidence/model/prompt_version`，分类只允许 `spoken/broll/highlight/uncategorized`。`highlights` 使用与 `usable_ranges` 相同的带 `start_seconds/end_seconds/label` 严格区间结构，9000 落库时转换为 `kind="highlight"`；两者都必须满足当前 `material_id` 且 `0 <= start < end <= duration_seconds`。未知字段和模型额外素材引用一律解析失败。

- [ ] **Step 3: 抽取最小共享注入检查**

把 `ai_edit_planner_service.py` 现有冻结模式原位移动到 `ai_edit_safety.py`，对外只暴露文本列表接口：

```python
def contains_prompt_injection(values: list[str]) -> bool:
    normalized = "\n".join(str(value or "").lower() for value in values)
    return any(pattern.search(normalized) for pattern in INJECTION_PATTERNS)
```

规划服务改为传入转写和镜头标签；素材分析服务传入转写文本和场景标签。先跑既有 planner 注入测试，证明行为不变。

- [ ] **Step 4: 实现一次多模态调用和严格解析**

当前 `OpenAICompatibleClient.chat()` 已允许 `messages: list[dict]`，但现有服务和测试隐含 content 为字符串。先在 `llm/client.py` 增加最小多模态合同测试，证明 `_post_json` 原样保留列表 content，响应解析仍只返回 `reply_text/model/usage`，普通字符串调用不回归；不新增第二个 LLM 客户端。

服务构造 OpenAI-compatible `content` 数组：一段 `{"type":"text","text":...}` 结构化文本和每张关键帧的 `{"type":"image_url","image_url":{"url":"data:image/...;base64,..."}}`。只调用一次 `OpenAICompatibleClient.chat()`；先复用既有注入检测，再 `json.loads` 和 Pydantic 校验。拒答、空输出、格式错误、越界结果分别返回稳定错误码，不生成规则兜底。

成功 HTTP 调用后按既有 planner 模式调用 `measure_chat_usage`，优先使用供应商真实 Token，并上报 `capability_key="compute"`；供应商无 usage 时构造单独的 `usage_messages`，只包含 system 文本、结构化文本消息和回复，不包含图片 data URI，再做估算。不能直接把含列表 content 的原始多模态 messages 交给当前 fallback，因为当前 helper 只统计字符串 content，会漏掉结构化用户文本；base64 图片始终不得进入计费 payload 或日志。

- [ ] **Step 5: 接通 9000 窄客户端**

```python
def analyze_ai_edit_material(self, request: dict) -> dict:
    return self._post_json("/internal/ai-edit/materials/analyze", request)
```

19000 → 9000 的提交 DTO 归 `app/schemas.py`，固定为：

```python
class LocalMaterialAnalysisSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    attempt_count: int = Field(..., ge=0)
    execution_token: str = Field(..., min_length=64, max_length=64)
    media_profile: MediaProfile
    transcript: list[TranscriptSegment] = Field(default_factory=list, max_length=100)
    scenes: list[SceneSummary] = Field(default_factory=list, max_length=100)
    stability: StabilitySummary | None = None
    keyframes: list[MaterialKeyframe] = Field(default_factory=list, max_length=12)
```

请求 JSON 编码后总量不得超过 8MB，禁止 `path/relative_path/storage_key/merchant_id` 字段。`app/routers/ai_edit.py` 的 9000 路由不能声明普通 Pydantic body 后才检查大小：先要求并校验 `Content-Length <= 8MB`，再用 `Request.stream()` 累计读取到 `8MB + 1` 立即 413，最后才 `json.loads + LocalMaterialAnalysisSubmit.model_validate`；`tests/test_phase12_task12_material_api.py` 固定无长度、声明超限、分块累计超限、畸形 JSON 和合法请求五条路由红灯。19000 只读取 Worker 返回的受管关键帧相对路径，逐张复验位于本次 task root、JPEG/WEBP 魔数、最大边 720px、解码后 512KB，再 base64 编码进 DTO；9000 重复执行相同校验并匹配当前 `source_sha256 + content_analysis attempt + execution_token`，然后构造 9100 请求。9000 不持久化 base64；从已校验首帧生成受控缩略图临时文件，9100 成功且数据库快照提交后才原子登记缩略图，失败保留本地三阶段结果并把 content_analysis 标为 failed。四组件替身测试覆盖 Worker → 19000 → 9000 → 9100、关键帧越界、9100 失败和无路径泄露。

9000 从可信素材和本地分析结果构造请求，成功后保存版本化快照；9100 失败只把 `content_analysis` 标为 `failed`，不回滚其他阶段。

- [ ] **Step 6: 运行并提交**

```powershell
python -m pytest tests/test_phase12_task12_material_semantic.py tests/test_phase12_task12_material_api.py tests/test_phase12_ai_edit_internal_api.py tests/test_phase12_ai_edit_planner.py tests/test_compute_usage_client.py -q
git add apps/xg_douyin_ai_cs/schemas.py apps/xg_douyin_ai_cs/routers/ai_edit.py apps/xg_douyin_ai_cs/services/ai_edit_safety.py apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py apps/xg_douyin_ai_cs/services/ai_edit_material_analysis_service.py apps/xg_douyin_ai_cs/llm/client.py app/schemas.py app/routers/ai_edit.py app/services/xg_douyin_ai_cs_client.py app/services/ai_edit_service.py tests/test_phase12_task12_material_semantic.py tests/test_phase12_task12_material_api.py tests/test_phase12_ai_edit_internal_api.py
git commit -m "功能：增加素材多模态语义分析"
```

---

## Task 12-6：9000 宝塔受控云端存储

**Files:**
- Modify: `app/services/ai_edit_storage.py`
- Modify: `app/routers/ai_edit.py`
- Modify: `app/routers/admin_ai_edit.py`
- Modify: `app/main.py`
- Modify: `app/local_agent_ai_edit_routes.py`
- Modify: `app/local_agent_main.py`
- Modify: `app/config.py`
- Modify: `.env.development.example`
- Modify: `.env.lan.example`
- Modify: `.env.production.example`
- Modify: `tests/test_phase12_task12_material_cloud.py`
- Create: `tests/test_phase12_task12_material_preview.py`
- Create: `app/services/ai_edit_preview_ticket.py`

- [ ] **Step 1: 写原子上传、Range 与商户隔离红灯**

覆盖视频/音频/图片允许后缀、未知/双后缀拒绝、大小不符、超过 `AI_EDIT_MAX_MATERIAL_BYTES`、SHA 格式/内容不符、断流、符号链接、中间目录重解析点、跨商户、重复上传同内容幂等、同键异内容拒绝覆盖、`Range: bytes=0-99` 返回 206、无本地/云端文件返回稳定错误。平台发布测试必须证明公共记录使用独立存储键，复制失败不产生可见半成品。

- [ ] **Step 2: 实现流式原子存储**

```python
from collections.abc import AsyncIterable
from dataclasses import dataclass

@dataclass(frozen=True)
class StoredMaterial:
    storage_key: str
    size_bytes: int
    sha256: str
    created_by_request: bool

def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def build_material_storage_key(merchant_id: str, material_id: str, suffix: str) -> str:
    if (not material_id or material_id.startswith(".")
            or any(char in material_id for char in "/\\:")):
        raise AiEditStorageError("MATERIAL_ID_INVALID")
    merchant_key = hashlib.sha256(merchant_id.encode("utf-8")).hexdigest()[:24]
    if not re.fullmatch(r"\.?[A-Za-z0-9]{2,5}", suffix):
        raise AiEditStorageError("MATERIAL_SUFFIX_NOT_ALLOWED")
    clean_suffix = suffix.lower().lstrip(".")
    if clean_suffix not in {
        "mp4", "mov", "avi", "mp3", "wav", "aac", "m4a",
        "jpg", "jpeg", "png", "webp",
    }:
        raise AiEditStorageError("MATERIAL_SUFFIX_NOT_ALLOWED")
    return f"materials/{merchant_key}/{material_id}/source.{clean_suffix}"

async def store_material_stream(*, root: Path, merchant_id: str, material_id: str,
                                chunks: AsyncIterable[bytes], expected_size: int,
                                expected_sha256: str, suffix: str,
                                max_bytes: int) -> StoredMaterial:
    if expected_size <= 0 or expected_size > max_bytes:
        raise AiEditStorageError("MATERIAL_SIZE_NOT_ALLOWED")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise AiEditStorageError("MATERIAL_SHA256_INVALID")
    storage_key = build_material_storage_key(merchant_id, material_id, suffix)
    target = resolve_ai_edit_storage_key(storage_key, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size == expected_size and _file_sha256(target) == expected_sha256:
            return StoredMaterial(storage_key, expected_size, expected_sha256, False)
        raise AiEditStorageError("MATERIAL_CLOUD_CONTENT_CONFLICT")
    fd, temp_name = tempfile.mkstemp(prefix=".upload_", dir=target.parent)
    digest, total = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as output:
            async for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                if total > expected_size or total > max_bytes:
                    raise AiEditStorageError("MATERIAL_SIZE_NOT_ALLOWED")
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != expected_size or digest.hexdigest() != expected_sha256:
            raise AiEditStorageError("MATERIAL_UPLOAD_INTEGRITY_FAILED")
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return StoredMaterial(storage_key=storage_key, size_bytes=total,
                          sha256=digest.hexdigest(), created_by_request=True)
```

这是存储核心函数；完整路由还必须从 Local Agent token 得到可信商户、从当前素材记录得到可信 SHA/媒体类型并更新阶段状态。同一 `storage_key` 用进程内 keyed lock 串行提交，`os.replace` 前后重新检查全部现存父目录非符号链接/重解析点。数据库失败时：`created_by_request=False` 绝不删文件；`True` 也不在请求内删除最终对象，而是向受控根下 `.orphan_uploads.json` 原子登记 `{storage_key, expected_sha256, created_at}`，不得只记内存/日志。Task 12-7 清理器读取严格清单，在超过 24 小时、确认无任何 metadata 引用且文件 SHA 仍匹配时清理；清单损坏则停止清理，避免并发请求误删。

9000 路由使用 `Request.stream()` 直接传给该函数。`AI_EDIT_MAX_MATERIAL_BYTES` 默认 `2147483648`，先校验 `Content-Length`，再在每个分块后校验累计大小，防伪造长度耗尽磁盘。存储键使用不可逆商户哈希目录，不把明文 `merchant_id` 放进存储键。扩展 `resolve_ai_edit_storage_key`，从受管根到目标父目录逐段拒绝符号链接和 Windows 重解析点，不能只检查最终路径段。重复上传仅在大小与 SHA 都一致时幂等成功，内容冲突不得覆盖现存文件。测试固定“幂等已有文件 + 数据库提交失败”原文件仍存在。

- [ ] **Step 3: 实现 19000 到 9000 流式上传**

`Nine000ControlClient.upload_material` 接收本机受管 `Path`，生产实现用标准库 `http.client` 发送原始请求体：

```python
def upload_material(self, *, merchant_id: str, material_id: str, source: Path,
                    expected_sha256: str, suffix: str,
                    attempt_count: int, execution_token: str) -> dict:
    token = _get_local_agent_token()
    if not token:
        raise RuntimeError("LOCAL_AGENT_TOKEN_NOT_CONFIGURED")
    parsed = urlsplit(server_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("SERVER_URL_INVALID")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("SERVER_URL_INVALID")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("SERVER_HTTPS_REQUIRED")
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=60)
    base_path = parsed.path.rstrip("/")
    upload_path = (
        f"{base_path}/ai-edit/materials/agent/"
        f"{quote(material_id, safe='')}/content"
    )
    try:
        connection.putrequest("PUT", upload_path)
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", str(source.stat().st_size))
        connection.putheader("X-Content-SHA256", expected_sha256)
        connection.putheader("X-Material-Suffix", suffix)
        connection.putheader("X-Material-Attempt", str(attempt_count))
        connection.putheader("X-Material-Execution-Token", execution_token)
        connection.putheader("X-Local-Agent-Token", token)
        connection.endheaders()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                connection.send(chunk)
        response = connection.getresponse()
        body = response.read(64 * 1024 + 1)
        if len(body) > 64 * 1024:
            raise RuntimeError("MATERIAL_UPLOAD_RESPONSE_TOO_LARGE")
        if response.status not in {200, 201}:
            raise RuntimeError(f"MATERIAL_UPLOAD_FAILED:{response.status}")
        return json.loads(body.decode("utf-8"))
    finally:
        connection.close()
```

所需 import 为 `HTTPConnection/HTTPSConnection`、`urlsplit/quote`、`json`，均来自标准库。非回环地址强制 HTTPS，禁止 URL 用户信息、query 与 fragment。`merchant_id` 必须等于本 Local Agent 启动时绑定的可信 `LOCAL_AGENT_MERCHANT_ID`，否则拒绝；请求 token 仍只由 `_get_local_agent_token()` 读取，9000 再以 token 映射复验归属。云端上传必须携带 cloud_upload 阶段的 `attempt_count + execution_token`，9000 在读取 body 前先校验令牌哈希。不得 `read_bytes()`，不得记录响应 body、token、源路径或完整 URL。9000 收流时状态为 `running`，原子提交后才写 `cloud_available/succeeded`；请求失败保持 `local_only/failed`。

- [ ] **Step 4: 实现云端预览和本地短票据**

9000 云端预览也先用带 Bearer 登录态的 JSON 请求签发 60 秒随机票据，再由媒体标签使用票据 URL；原因是当前浏览器认证 token 在 `sessionStorage`，`<video>/<audio>/<img>` 不能自行附加 Authorization 头。票据只绑定商户、素材、当前 SHA 和到期时间，内容接口支持单区间 Range 与 `Accept-Ranges: bytes`，不能改成长期公开 URL。9000 access log 与错误日志不得记录票据值。

本地预览同样先用带 Local Agent token 的 JSON 请求签发 60 秒随机票据，再由媒体标签使用票据 URL；票据只绑定商户、素材、当前 SHA 和到期时间，Local Agent access log 不记录票据值。

由于媒体标签会连续发多个 Range 请求，9000 与 19000 的票据使用 `secrets.token_urlsafe(32)`，在 60 秒内允许同素材重复使用，不能首请求即销毁；比较使用 `secrets.compare_digest`。两端票据存储均为进程内有界 TTL 映射，最多 1000 条，签发或读取时惰性清理过期项；不新增数据库表。`app/local_agent_main.py` 给 `uvicorn.access` 增加窄过滤器，只对本地预览路径移除 query；9000 主应用给 `uvicorn.access` 增加同形过滤，覆盖 `/ai-edit/materials/content?`：

```python
class LocalPreviewAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 5:
            args = list(record.args)
            path = str(args[2])
            if (
                path.startswith("/agent/ai-edit/materials/preview?")
                or path.startswith("/ai-edit/materials/content?")
            ):
                args[2] = path.split("?", 1)[0] + "?ticket=[REDACTED]"
                record.args = tuple(args)
        return True
```

两端票据响应固定 `Cache-Control: no-store`、`Referrer-Policy: no-referrer`。测试分别捕获两端 `uvicorn.access`，断言随机票据原值不在日志。19000 预览 `OPTIONS/GET` 继续使用现有回环 CORS/PNA 策略；9000 走当前前端同源 `/api` 代理，不新增跨域例外。当前仓库不管理生产 Nginx，本地检查点 B 只验证 uvicorn 脱敏；宝塔执行包必须额外验证该内容路径的 Nginx access log 不记录 query，未验证前 concern 保持 `baota_ai_edit_production_not_verified`。

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

新增 `AI_EDIT_CLOUD_STORAGE_ROOT` 与 `AI_EDIT_MAX_MATERIAL_BYTES`，开发/局域网/生产示例均为空或测试值说明，不写客户真实路径。平台公共素材发布在本任务补齐：发布前要求源素材当前 SHA 的本地分析成功且 `storage_mode=cloud_available`，只从已验证私有云端对象流式复制到独立平台存储键，复制后复验大小与 SHA，再在单次数据库事务中写 `scope=platform, merchant_id=NULL` 和复制后的最新分析快照；禁止数据库记录直接复用商户私有 `cloud_storage_key`，任一步失败不得留下可见半成品。运行：

```powershell
python -m pytest tests/test_phase12_task12_material_cloud.py tests/test_phase12_task12_material_preview.py tests/test_phase12_ai_edit_api.py tests/test_phase12_local_ai_edit_routes.py -q
```

- [ ] **Step 6: 提交并硬暂停检查点 B**

```powershell
git add app/services/ai_edit_storage.py app/services/ai_edit_preview_ticket.py app/routers/ai_edit.py app/routers/admin_ai_edit.py app/main.py app/local_agent_ai_edit_routes.py app/local_agent_main.py app/config.py .env.development.example .env.lan.example .env.production.example tests/test_phase12_task12_material_cloud.py tests/test_phase12_task12_material_preview.py
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

覆盖：恢复后重新出现在 active；永久删除活动引用得 409；回收期保留本地/云端；到期后 9000 清云端并把 `purge_after` 置空形成不可见 tombstone；19000 按本地清单的 `purge_after` 在下次启动清本机；重复软删不延长窗口；重复恢复/清理幂等；本地已删后 finalize 失败会持久化并在重启补偿；跨商户 404。

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
    record = _find_manifest_strict(root, material_id)
    path = resolve_managed_relative_path(root, record["relative_path"])
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

永久删除必须读取严格清单中的 `relative_path`，经商户根 `resolve + relative_to` 和逐段重解析点检查后删除，不能调用旧的无后缀 `resolve_managed_material_path()`。只删除受管文件和已验证为空的素材目录，拒绝递归删除商户根；MP4、WAV、JPEG 三类各有真实清理测试。

同时把现有 `soft_delete_material` 收紧为同商户幂等：已在回收站时返回原 `deleted_at/purge_after`，不把 7 天窗口向后刷新。`restore_material` 对活动素材幂等成功；`purge_material` 对文件已不存在但清单仍存在的恢复场景继续删除清单，不能因 `missing_ok` 掩盖活动引用校验。

- [ ] **Step 3: 实现 19000 协调与 9000 幂等状态机**

恢复顺序：本地恢复 → 9000 恢复；9000 失败则用操作前 `deleted_at/purge_after` 快照回滚本地软删。永久删除顺序：9000 prepare 校验活动引用 → 本地清理 → 9000 finalize 再校验并删除云端、清空 `purge_after/cloud_storage_key`、置 `storage_mode=local_missing`，保留不可见审计 tombstone。prepare 后素材保持已删除，不能产生新任务引用。

9000 `prepare` 在单次事务中校验已软删、无活动引用、`purge_status IS NULL`，生成随机 `operation_id=secrets.token_hex(32)` 并原子写 `purge_status=preparing/purge_operation_id`；同一 operation 重放幂等，其他操作 409。`purge_status=preparing` 时恢复、新任务引用和第二次删除均拒绝。19000 在本地清理前原子持久化 `pending_purge_finalize`，9000 `finalize` 必须恒定时间匹配 operation ID；成功清云端后保留 `purge_status=completed` 和最后 `purge_operation_id` 在不可见 tombstone 中，不清空 claim，从而同一 finalize 在响应丢失后返回既有成功，其他 operation 仍冲突。进程在本地删除后崩溃时，启动恢复只补 finalize，不尝试恢复已删除文件。9000 prepare 失败不得碰本地文件，9000 finalize 失败不得把前端显示为“永久删除完成”。

- [ ] **Step 4: 实现有界清理调度器**

`AiEditMaterialCleanupScheduler` 复用现有 scheduler 的 `start/stop/run_once` 形态，每次最多处理 `AI_EDIT_MATERIAL_CLEANUP_BATCH_SIZE` 条到期素材。9000 只清理云端并保留 tombstone；19000 启动时独立扫描本地清单清理到期文件，两端都按 `purge_after` 幂等收敛，永久删除 claim 仍以 9000 `purge_status/purge_operation_id` 为准。默认开发关闭，生产示例仍保持 `false`，Phase 13 配置窗口显式开启。`run_once()` 可在本地测试直接调用；单条失败不阻断批次。清理器同时处理超过 24 小时且无任何 metadata 引用的云端孤儿文件，删除前复验存储键、SHA 与父目录安全。`app/main.py` 只在显式启用时于 startup 调 `start()`，shutdown 无条件 `stop()`；不得在 import 或测试 collection 时启动后台线程。

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
- Modify: `frontend/src/features/ai-edit/pages/AiVideoEditor.tsx`
- Modify: `apps/ai_edit/contracts.py`
- Modify: `app/services/ai_edit_service.py`
- Modify: `app/local_agent_ai_edit_routes.py`
- Modify: `tests/test_phase12_ai_edit_service.py`
- Modify: `tests/test_phase12_local_ai_edit_routes.py`
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

9000 API 增加带筛选分页的列表、详情、缩略图、人工确认和超管发布；19000 API 增加分析、上传、增稳、恢复、永久删除和预览票据。方法名与 URL 必须逐项对应 §1.6，所有 Local API 都要求显式 `merchantId`。现有 `apiClient` 已把 Axios 响应解成 `{success,data,message}`，`features/ai-edit/api.ts` 继续只通过当前 `unwrap()` 再取一层 `data`，禁止直接返回 `resp` 或多解包一层。前端 `AiEditMaterial.media_type` 固定为 `video | audio | image`，不能继续用任意字符串。

工作台角色按现有视频合同收口，不新增角色枚举：Task 12 只有 `video` 可选 `main/broll/pip_replacement`；`image/audio` 一期仅作为素材库可预览、分析和管理素材，不进入当前 `AiEditJobMaterial`，直到静帧/BGM 渲染合同单独设计。`AiVideoEditor.tsx` 对图片和音频禁用“用于剪辑”；9000 `create_job` 和 WorkerManifest 再次要求任务素材 `media_type=video`，防绕过前端。此边界不提前扩渲染协议。

- [ ] **Step 2: 实现页面组件**

`MaterialLibrary.tsx` 只编排状态与数据请求；筛选、网格、详情、时间轴、导入队列各自独立。`Index.tsx` 只用现有 `isSuperAdmin(user)` helper 计算 `canManagePlatform` 并与 `merchantId` 一起传给素材库，不新增用户字段，不修改全局导航或路由分发。平台管理入口仅在 `canManagePlatform=true` 时渲染，后端仍独立强校验。保留现有 header 与：

```tsx
<ModuleTabs items={[
  { label: "素材库", path: "/ai-edit/materials" },
  { label: "剪辑工作台", path: "/ai-edit/editor" },
]} />
```

内容区桌面使用 `grid-template-columns: 196px minmax(0,1fr) 360px`；移动端小于 768px 改单栏，筛选抽屉和全屏详情。颜色只使用现有 `#f3f6fa/#e4e8f0/#1a1f2e/#2563eb` 及既有状态色。

- [ ] **Step 3: 实现真实导入和批量操作**

文件选择器同时支持 `multiple` 与独立文件夹入口，accept 覆盖设计批准的 `video/*,audio/*,image/*`；拖拽复用同一队列。队列逐项保存 `validating/deduplicating/importing/queued/succeeded/failed/existing`。导入保持现有顺序流式上传，一项完成并拿到 9000 规范素材 ID 后才处理下一项；分析、上传云端、删除等后置批量操作并发上限 2，使用 `Promise.allSettled` 或等价逐项收集保留每项错误，禁止单项失败导致整批丢失。批次结束只刷新一次列表。

19000 导入响应后队列始终切换到规范 `material_id`，但只按 `disposition` 决定显示：`created=导入成功`、`existing=已存在`、`restored=已从回收状态恢复`；禁止用“ID 是否改变”判断重复。不能继续以临时 ID 调分析、上传或详情。平台公共素材采用“私有素材已完成分析和云端上传 → 超管发布”的入口，不从浏览器向 19000 传超管身份。

- [ ] **Step 4: 实现预览、状态与人工确认**

本地可用时请求 19000 短票据，云端可用时请求 9000 短票据。视频用 `<video>`、音频用 `<audio>`、图片用 `<img>`；三者的 URL 只含 60 秒随机票据，不含 Bearer token 或 Local Agent token。组件卸载、切换素材或票据失败时立即清空旧媒体 URL，防跨商户会话残留。卡片只显示两个最高优先级状态；详情展示五阶段，不适用阶段显示“不需要”。`queued` 显示“待处理”，不得把 `pending` 显示为“处理中”。时间轴只对视频/音频开放，并只允许在 `0 <= start < end <= duration` 内编辑；图片只编辑分类、标签和说明，保存后标记“人工确认”。

- [ ] **Step 5: 运行合同、构建与布局检查**

```powershell
node frontend/scripts/check-phase12-task12-material-library-contract.mjs
npm --prefix frontend run build
python -m pytest tests/test_phase12_ai_edit_service.py tests/test_phase12_local_ai_edit_routes.py tests/test_phase12_ai_edit_worker_contract.py -q
```

启动前端开发服务器后运行：

```powershell
node frontend/scripts/check-phase12-task12-material-library-layout.mjs http://127.0.0.1:5173
```

布局脚本必须拦截 9000/19000，覆盖 1280×800 与 375×667，检查私有/平台/回收站、网格/列表、详情、导入队列、移动抽屉，并断言无横向溢出、按钮遮挡、控制台错误和空白媒体区域。

- [ ] **Step 6: 提交**

```powershell
git add frontend/src/features/ai-edit/types.ts frontend/src/features/ai-edit/api.ts frontend/src/features/ai-edit/localApi.ts frontend/src/features/ai-edit/pages/MaterialLibrary.tsx frontend/src/features/ai-edit/pages/AiVideoEditor.tsx frontend/src/pages/Index.tsx frontend/src/features/ai-edit/components/MaterialFilters.tsx frontend/src/features/ai-edit/components/MaterialGrid.tsx frontend/src/features/ai-edit/components/MaterialDetail.tsx frontend/src/features/ai-edit/components/MaterialTimeline.tsx frontend/src/features/ai-edit/components/ImportQueue.tsx frontend/scripts/check-phase12-task12-material-library-contract.mjs frontend/scripts/check-phase12-task12-material-library-layout.mjs apps/ai_edit/contracts.py app/services/ai_edit_service.py app/local_agent_ai_edit_routes.py tests/test_phase12_ai_edit_service.py tests/test_phase12_local_ai_edit_routes.py
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

使用临时 SQLite、临时本机目录、临时云端目录、替身 9100 和真实 FastAPI TestClient，分别用合成视频、合成 WAV 和小型 JPEG 验证：导入去重 → 自动分析 → 五阶段按媒体类型收敛 → 人工确认 → 云端上传 → 本地/云端预览 → 回收站 → 恢复 → 到期清理。另覆盖增稳衍生素材、平台公共发布、9100 失败只影响内容分析、19000 重启恢复、旧 attempt 409 和跨商户 404。检查点 C 必须同时证明：前端对音频/图片不提供可用的“用于剪辑”操作；直接绕过前端向 9000 创建任务传音频或图片得稳定 422/409；伪造 WorkerManifest 放入非视频素材被严格 schema/预检拒绝。

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
    monkeypatch.setattr("httpx.AsyncClient.request", blocked)
    monkeypatch.setattr("requests.sessions.Session.request", blocked)
    monkeypatch.setattr("http.client.HTTPConnection.connect", blocked)
    monkeypatch.setattr("http.client.HTTPSConnection.connect", blocked)
    monkeypatch.setattr("socket.create_connection", blocked)
    yield
    assert calls == []
```

测试中的内部 HTTP 必须用 TestClient/替身注入，不通过真实 socket。因为 Task 12-6 生产上传使用 `http.client`，只拦 urllib/httpx/requests 会形成假绿；上述三层哨兵必须保留，并增加一个故意调用 `HTTPConnection.connect()` 能触发哨兵的自检测试。

- [ ] **Step 3: 合成媒体 smoke**

脚本用 FFmpeg 生成 3 秒带音频竖屏视频，执行 ffprobe、场景/关键帧/稳定性替身与云端临时目录上传。输出必须明确写“本地合成媒体 smoke”，不得声称真实模型或宝塔通过。

- [ ] **Step 4: 运行最终矩阵**

```powershell
python -m pytest tests/test_phase12_task12_material_schema.py tests/test_phase12_task12_duplicate_audit.py tests/test_phase12_task12_material_api.py tests/test_phase12_task12_material_analysis.py tests/test_phase12_task12_material_semantic.py tests/test_phase12_task12_material_cloud.py tests/test_phase12_task12_material_preview.py tests/test_phase12_task12_material_lifecycle.py tests/test_phase12_task12_cleanup_scheduler.py tests/test_phase12_task12_material_e2e.py tests/test_phase12_task12_no_network.py tests/test_phase12_local_material_supervisor.py -q
python -m pytest tests/test_phase12_ai_edit_schema.py tests/test_phase12_ai_edit_api.py tests/test_phase12_ai_edit_service.py tests/test_phase12_ai_edit_internal_api.py tests/test_phase12_ai_edit_pipeline.py tests/test_phase12_local_ai_edit_routes.py tests/test_phase12_local_ai_edit_supervisor.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py -q
python scripts/smoke_phase12_task12_material_synthetic.py
node frontend/scripts/check-phase12-task12-material-library-contract.mjs
npm --prefix frontend run build
```

随后真实执行布局检查并保证清理进程，不能只在 Task 12-8 跑一次后口头继承：

```powershell
$occupied = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if ($occupied) { throw '5173 已被占用，拒绝误杀非本轮进程' }
$vite = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d','/s','/c','npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173') -PassThru -WindowStyle Hidden
try {
  $ready = $false
  1..30 | ForEach-Object {
    if (-not $ready) {
      try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173 -TimeoutSec 1 | Out-Null; $ready = $true } catch { Start-Sleep -Seconds 1 }
    }
  }
  if (-not $ready) { throw "Vite 未在 30 秒内就绪" }
  node frontend/scripts/check-phase12-task12-material-library-layout.mjs http://127.0.0.1:5173
  if ($LASTEXITCODE -ne 0) { throw "Task 12 布局检查失败" }
} finally {
  if ($vite) { & taskkill.exe /PID $vite.Id /T /F 2>$null | Out-Null }
  $released = $false
  1..20 | ForEach-Object {
    if (-not $released) {
      $listeners = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
      if (-not $listeners) { $released = $true } else { Start-Sleep -Milliseconds 250 }
    }
  }
  if (-not $released) {
    $owners = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerPid in $owners) { & taskkill.exe /PID $ownerPid /T /F 2>$null | Out-Null }
    Start-Sleep -Seconds 1
  }
  if (Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Vite 进程树终止后 5173 仍未释放'
  }
}
```

布局脚本输出的桌面/移动截图路径、0 控制台错误和 `5173` 已释放证据原样进入检查点 C 回传。端口前检保证兜底清理只会处理本轮启动的 Vite 进程树。

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
- Modify: `phase12_test_launcher.spec`
- Modify: `app/phase12_test_launcher.py`
- Modify: `app/local_agent_build_info.py`
- Modify: `scripts/smoke_phase12_task11_real.py`
- Create: `scripts/smoke_phase12_task12_material_exe.py`
- Modify: `docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md`
- Modify: `docs/ai/05_PROJECT_CONTEXT.md`

- [ ] **Step 1: 固定打包依赖与资源**

`requirements-ai-edit-worker.txt` 增加固定版本 `scenedetect==0.6.7.1`；Worker spec 显式收集 `funasr/cv2/scenedetect` 及 Task 12 新模块，仍排除 FastAPI/uvicorn。离线 ASR 资源冻结为 ModelScope 模型 `iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`，本机已探索来源目录为 `C:\Users\A\.cache\modelscope\hub\models\iic\speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`；执行窗口通过环境变量 `PHASE12_FUNASR_MODEL_DIR` 指向经审批的同版本目录，不得联网下载或任选模型。

构建强校验下列允许清单，任何一项不符即停止；只复制清单内运行必需文件，不复制 `.mdl/.msc/.mv`、README、示例音频、图片或任何未知附加文件：

```text
configuration.json|478|1ACAC324430B5A4680EF5EE2947575443AB2039A92C8A0551665F6BC9A606B41
config.yaml|3477|6602EFA95E4C7248E1D1030F7FF454A3C9AF0F57C335ED87F35260CD7FAEC35D
model.pt|989763045|3D491689244EC5DFBF9170EF3827C358AA10F1F20E42A7C59E15E688647946D1
am.mvn|11203|29B3C740A2C0CFC6B308126D31D7F265FA2BE74F3BB095CD2F143EA970896AE5
seg_dict|8287834|59A2EF803A3F1648AD03A2E1480DB1C1EE0C0D7DC4EF4DBD16CEA33944329022
tokens.json|93676|2B20C2B12572D682AFFF84CE1C8D560F67B8B32A4C1F21567411D141ED352127
```

“文件存在”不是充分门禁。构建前用 Python 3.11 在禁网哨兵下执行一次 `AutoModel(model=<资源目录>, device="cpu", disable_update=True)` 初始化，并用 FFmpeg 生成 1 秒本地 WAV 做最小 `generate(..., sentence_timestamp=True)`；初始化、推理或任何网络尝试失败都停止构建。打包后 EXE smoke 再跑同一离线样本，防止 PyInstaller 漏收配置、词表或模型旁文件。不得把 token、客户路径或数据库写入包，运行时设置 `AI_EDIT_ASR_MODEL_DIR` 为包内目录并禁止在线更新。

构建脚本校验后只把允许清单文件从 `$env:PHASE12_FUNASR_MODEL_DIR` 复制到 `$BundleDir/models/funasr`；`phase12_test_launcher.spec` 逐文件收进外层 EXE，并拒绝 bundle 模型目录出现未知文件。`phase12_test_launcher.py` 用 `_resolve_resource("models/funasr")` 定位并在 `_agent_env` 写入 `AI_EDIT_ASR_MODEL_DIR`，Local Agent 的 `_build_worker_env()` 保留该非敏感路径传给 Worker。缺目录时启动器在启动 19000 前明确报错，不能等用户导入后才失败。

构建前由构建脚本生成 `app/local_agent_build_info.py` 的 `BUILD_VERSION/BUILD_TIME/GIT_COMMIT`，禁止新 EXE 继续报告 `P0-LOCAL-AGENT-EXE-1`。版本固定 `PHASE12-TASK12-TEST-1`，提交哈希取构建前源码 HEAD；smoke 断言 `/runtime/status` 返回该版本。该生成文件随 Task 12-10 源码一起提交，构建时间作为本次交付事实允许变化。

- [ ] **Step 2: 重建唯一测试 EXE**

```powershell
$Python310Exe = $env:PHASE12_PYTHON310_EXE
$Python311Exe = $env:PHASE12_PYTHON311_EXE
$FfmpegDir = $env:PHASE12_FFMPEG_DIR
$FunAsrModelDir = $env:PHASE12_FUNASR_MODEL_DIR
if (-not (Test-Path $Python310Exe)) { throw "PHASE12_PYTHON310_EXE 无效" }
if (-not (Test-Path $Python311Exe)) { throw "PHASE12_PYTHON311_EXE 无效" }
if (-not (Test-Path (Join-Path $FfmpegDir 'ffmpeg.exe'))) { throw "PHASE12_FFMPEG_DIR 无效" }
if (-not (Test-Path (Join-Path $FunAsrModelDir 'configuration.json'))) { throw "PHASE12_FUNASR_MODEL_DIR 无效" }
powershell -ExecutionPolicy Bypass -File scripts/build_phase12_single_test_exe.ps1 `
  -Python310Exe $Python310Exe `
  -Python311Exe $Python311Exe `
  -FfmpegDir $FfmpegDir `
  -TestApiUrl https://merchant.xiaogaoai.cn/api `
  -TestFrontendUrl https://merchant.xiaogaoai.cn/ `
  -MerchantId m_nc_2bba00063cc13016
```

执行窗口必须在当前 PowerShell 会话设置四个环境变量；实际路径不得写入 Git。输出仍只有 `dist/phase12-task11/小高AI系统测试版.exe`，禁止产生第二个交付 EXE。

- [ ] **Step 3: 真实本机 EXE smoke**

启动 EXE 后验证：`/health` 200、19000 鉴权三态、AI 素材路由注册、离线 FunASR 模型初始化与本地 WAV 推理、合成视频/音频/JPEG 导入后自动分析按媒体类型收敛、本地预览 Range、临时云端目录上传、回收站恢复、Worker 进程退出和 19000 端口释放。这里的“真实模型”仅指随包离线 ASR；不得连接真实宝塔或真实付费多模态模型。

- [ ] **Step 4: 回归、哈希与文档**

```powershell
python -m pytest tests/test_phase12_task11_launcher.py tests/test_phase12_task12_material_e2e.py tests/test_phase12_local_ai_edit_routes.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py -q
Get-FileHash -Algorithm SHA256 -LiteralPath 'dist/phase12-task11/小高AI系统测试版.exe'
```

交付报告原位替换 EXE 大小、SHA、Task 12 smoke 结果和限制；旧 SHA 不得继续作为当前值保留。

- [ ] **Step 5: 提交源码与报告**

```powershell
git add requirements-ai-edit-worker.txt ai_edit_worker.spec scripts/build_phase12_single_test_exe.ps1 phase12_test_launcher.spec app/phase12_test_launcher.py app/local_agent_build_info.py scripts/smoke_phase12_task11_real.py scripts/smoke_phase12_task12_material_exe.py docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md docs/ai/05_PROJECT_CONTEXT.md
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
