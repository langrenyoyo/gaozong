# AI 自动回复 outbox PostgreSQL/MVCC 重启恢复验证实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地专用 PostgreSQL 测试库中验证 outbox 的跨进程可见性、20 路领取竞争、租约恢复、发送对账与旧 Worker 防覆盖语义，且不触发任何真实外部动作。

**Architecture:** 扩展现有有限命令 Worker，使其通过 `--postgres-smoke` 从安全的 `SMOKE_DATABASE_URL` 读取专用测试库；新增一份 PostgreSQL 专项 pytest，由父进程用文件门禁同步 20 个子进程。PostgreSQL schema 只走 Alembic，测试数据按唯一 namespace 精确清理，业务或迁移缺陷只回传 `REPAIR_REQUIRED`，不在本任务修复。

**Tech Stack:** Python 3.14、pytest、SQLAlchemy 2、psycopg 3、Alembic、PostgreSQL 16、Windows subprocess、Docker Compose dev profile

---

## 执行合同

- Task-ID：`DY-CS-AUTO-REPLY-OUTBOX-PG-MVCC-RECOVERY-1`
- Plan-Revision：`R1`
- Risk-Level：`HIGH`
- Integration-Base：`f751985090c348d92bed6f1873952dc572b44659`
- Approved-Spec-Head：`70f3e22b175e415ec6b1824e1e8f2e6a0a96ea6d`（含初始规格 `b1f5d28d60744ecf54bedf520682cbf270931344` 与连接边界勘误 `55f094d247f6a75f2d54bdae80739f336475000b`）
- Implementation-Base：`70f3e22b175e415ec6b1824e1e8f2e6a0a96ea6d`
- 执行方式：项目原地执行，不开 worktree、不新建分支、不切目录。

**实现增量允许文件：**

- Modify: `tests/helpers/outbox_restart_worker.py`
- Create: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`

**最终集成范围允许文件：**

- `docs/superpowers/specs/2026-07-25-ai-auto-reply-outbox-postgres-mvcc-recovery-design.md`
- `tests/helpers/outbox_restart_worker.py`
- `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`

**禁止事项：**

- 不修改 `app/`、模型、迁移、Compose、环境模板、配置或现有 SQLite 测试文件。
- 不修改、不取消暂存、不提交三份 `docs/superpowers/plans/` 治理计划。
- 不连接默认开发库、staging、production 或非白名单 host。
- 不把真实 URL、真实密码或 token 写入 argv、日志、断言、文档或提交信息；计划中的 `change_me` 仅是仓库既有开发占位值。
- 除专用 PostgreSQL 数据库连接外，不调用 LLM、9100、抖音、微信或其他 socket，不发送真实消息。
- 不自动停止或删除 Docker 容器、数据库、volume。
- 发现业务或 0016 缺陷时停止并回传 `REPAIR_REQUIRED`，不得顺手修改。

### Task 1: 建立 PostgreSQL 安全门与 Worker 合同测试

**Files:**
- Create: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`
- Test: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`

- [ ] **Step 1: 写入 Worker 模块加载器和安全 URL 合同测试**

先创建测试文件，加入以下最小合同。测试通过 `importlib` 加载 Worker，不导入 `app.database`：

```python
"""AI 自动回复 outbox PostgreSQL/MVCC 跨进程验证。"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "tests" / "helpers" / "outbox_restart_worker.py"


def _load_worker_module():
    spec = importlib.util.spec_from_file_location("outbox_restart_worker_pg_contract", WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p1_worker_cli_exposes_fixed_postgres_mode_without_url_argument():
    result = subprocess.run(
        [sys.executable, str(WORKER), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "--postgres-smoke" in result.stdout
    assert "--namespace" in result.stdout
    assert "--ready-file" in result.stdout
    assert "--start-file" in result.stdout
    assert "--lease-owner" in result.stdout
    assert "--database-url" not in result.stdout


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///tmp.db",
        "postgresql+psycopg://u:p@10.0.0.5:5432/auto_wechat_outbox_test",
        "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat",
        "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat_outbox_test?sslmode=require",
        "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat_outbox_test#fragment",
    ],
)
def test_p1_worker_rejects_unsafe_postgres_targets(url):
    worker = _load_worker_module()
    with pytest.raises(ValueError):
        worker._validate_smoke_database_url(url)


def test_p1_worker_accepts_only_dedicated_local_database():
    worker = _load_worker_module()
    url = "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat_outbox_test"
    assert worker._validate_smoke_database_url(url) == url
```

- [ ] **Step 2: 运行合同测试并确认先失败**

Run:

```powershell
python -m pytest tests/test_ai_auto_reply_outbox_postgres_mvcc.py -q
```

Expected: FAIL，原因必须是缺少 `--postgres-smoke` 或 `_validate_smoke_database_url`，而不是导入数据库、网络连接或语法错误。

- [ ] **Step 3: 确认未意外修改其他文件**

Run:

```powershell
git status --short
```

Expected: 除三份既有治理计划外，仅新增 `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`。

### Task 2: 扩展有限命令 Worker 支持安全 PostgreSQL 模式

**Files:**
- Modify: `tests/helpers/outbox_restart_worker.py`
- Test: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`
- Test: `tests/test_ai_auto_reply_outbox_restart_recovery.py`

- [ ] **Step 1: 增加标准 URL 解析和固定安全门**

在 Worker 顶部增加标准 SQLAlchemy URL 解析；不新增依赖：

```python
import time
from contextlib import ExitStack

from sqlalchemy.engine import make_url


_PG_ALLOWED_HOSTS = {
    "127.0.0.1",
    "localhost",
    "postgres",
    "auto-wechat-postgres-dev",
}
_PG_TEST_DATABASE = "auto_wechat_outbox_test"


def _validate_smoke_database_url(url: str) -> str:
    if not url:
        raise ValueError("SMOKE_DATABASE_URL 未设置")
    if "?" in url or "#" in url:
        raise ValueError("SMOKE_DATABASE_URL 禁止 query 或 fragment")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg":
        raise ValueError("SMOKE_DATABASE_URL 必须使用 postgresql+psycopg")
    if parsed.host not in _PG_ALLOWED_HOSTS:
        raise ValueError("SMOKE_DATABASE_URL host 不在本地白名单")
    if parsed.database != _PG_TEST_DATABASE:
        raise ValueError("SMOKE_DATABASE_URL 必须指向 auto_wechat_outbox_test")
    return url
```

- [ ] **Step 2: 把 SQLite 路径与 PostgreSQL 模式改为互斥参数**

在 `_parser()` 中把原 `--database` 替换为互斥组，并新增有限参数和唯一动作：

```python
database = parser.add_mutually_exclusive_group(required=True)
database.add_argument("--database")
database.add_argument("--postgres-smoke", action="store_true")
parser.add_argument("--namespace", default="restart_test")
parser.add_argument("--ready-file")
parser.add_argument("--start-file")
parser.add_argument("--lease-owner")
```

在 action choices 中只新增：

```python
"claim-once", "guarded-block-once"
```

不得增加任意 SQL、URL、模块或表达式参数。

- [ ] **Step 3: 在导入 app.database 前绑定后端**

将 `_configure_environment()` 收敛为：

```python
def _configure_environment(args: argparse.Namespace) -> str:
    if args.postgres_smoke:
        database_url = _validate_smoke_database_url(
            os.environ.get("SMOKE_DATABASE_URL", "").strip()
        )
        env_dir = Path(args.log).resolve().parent
        backend = "postgresql"
    else:
        db_path = Path(args.database).resolve()
        database_url = f"sqlite:///{db_path.as_posix()}"
        env_dir = db_path.parent
        backend = "sqlite"
    os.environ["AUTO_WECHAT_ENV_FILE"] = str(env_dir / "missing.env")
    os.environ["APP_ENV"] = "development"
    os.environ["DATABASE_URL"] = database_url
    os.environ["AI_AUTO_REPLY_OUTBOX_ENABLED"] = "false"
    os.environ["DOUYIN_AUTO_REPLY_ENABLED"] = "false"
    os.environ["DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED"] = "false"
    return backend
```

`main()` 保存返回的 backend。仅 SQLite 执行：

```python
if backend == "sqlite":
    Base.metadata.create_all(bind=engine)
```

PostgreSQL 不得调用 `create_all`。

- [ ] **Step 4: 保持 SQLite socket 守卫并允许唯一 PostgreSQL 数据库传输**

把 `_run_safe_cycle` 增加 keyword-only `backend` 参数。已知业务外部入口在两个后端都必须 patch 为调用即失败；全局 `socket.socket.connect` 只在 SQLite 模式 patch，因为 PostgreSQL 自身需要数据库传输：

```python
with ExitStack() as stack:
    stack.enter_context(
        patch.object(dry_run, "_run_with_session_for_outbox", side_effect=_safe_handler)
    )
    stack.enter_context(
        patch.object(dry_run, "get_xg_douyin_ai_cs_client", side_effect=_forbidden_external)
    )
    stack.enter_context(
        patch.object(send_service, "_send_private_message_with_context", side_effect=_forbidden_external)
    )
    if backend == "sqlite":
        stack.enter_context(
            patch("socket.socket.connect", side_effect=_forbidden_external)
        )
    run_outbox_cycle()
```

`cycle` 动作必须调用 `_run_safe_cycle(db, args.audit, backend=backend)`。返回字段继续保留 `external_calls`，语义为业务外部调用计数；PostgreSQL 专用数据库连接不计入该值。安全 URL 守卫保证数据库传输只能指向固定本地测试库。

- [ ] **Step 5: 让测试数据使用唯一 namespace**

在 seed、claim-crash 等创建 `AiAutoReplyRun` 的动作中使用：

```python
merchant_id = f"outbox_pg_test_{args.namespace}"
account_open_id = f"outbox_pg_account_{args.namespace}"
trigger_event_key = f"{args.namespace}-{args.action}-{os.getpid()}-{datetime.now().timestamp()}"
```

保持 SQLite 默认 namespace 兼容现有 R1-R11；不得改变现有状态断言。

- [ ] **Step 6: 实现 claim-once 文件门禁**

加入有限等待 helper：

```python
def _wait_for_start(
    ready_file: str | None,
    start_file: str | None,
    *,
    gate_root: Path,
) -> None:
    if not ready_file or not start_file:
        raise ValueError("claim-once 需要 ready-file 和 start-file")
    ready = Path(ready_file).resolve()
    start = Path(start_file).resolve()
    root = gate_root.resolve()
    if ready.parent != root or start.parent != root:
        raise ValueError("ready/start 文件必须位于当前 pytest 临时目录")
    ready.write_text(str(os.getpid()), encoding="utf-8")
    deadline = time.monotonic() + 15
    while not start.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("claim start gate timeout")
        time.sleep(0.02)
```

`claim-once` 只调用一次真实 claim：

```python
if args.action == "claim-once":
    from app.services.ai_auto_reply_outbox_service import claim_next_batch
    _wait_for_start(
        args.ready_file,
        args.start_file,
        gate_root=Path(args.log).resolve().parent,
    )
    claimed = claim_next_batch(db, batch_size=1)
    _emit(
        pid=os.getpid(),
        action=args.action,
        run_ids=[run.id for run in claimed],
        lease_owners=[run.lease_owner for run in claimed],
    )
    return 0
```

- [ ] **Step 7: 实现 guarded-block-once 固定旧租约动作**

该动作不接受任意状态或 values，只允许尝试从 processing 写固定 blocked 终态：

```python
if args.action == "guarded-block-once":
    if not args.run_id or not args.lease_owner:
        raise ValueError("guarded-block-once 需要 run-id 和 lease-owner")
    from app.services.ai_auto_reply_outbox_service import (
        _guarded_lease_update,
        _set_outbox_lease_owner,
    )
    _set_outbox_lease_owner(args.lease_owner)
    try:
        rowcount = _guarded_lease_update(
            db,
            args.run_id,
            expected_status="processing",
            values={
                "status": "blocked",
                "block_reason": "pg_stale_worker_must_not_write",
                "lease_owner": None,
                "lease_expires_at": None,
            },
        )
    finally:
        _set_outbox_lease_owner("")
    _emit(pid=os.getpid(), action=args.action, rowcount=rowcount)
    return 0
```

- [ ] **Step 8: 运行合同测试与 SQLite 回归**

Run:

```powershell
python -m pytest tests/test_ai_auto_reply_outbox_postgres_mvcc.py -q
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
```

Expected: PostgreSQL 静态合同测试 PASS；SQLite `11 passed, 0 failed`。

- [ ] **Step 9: 提交 Worker 合同增量**

Run:

```powershell
git add -- tests/helpers/outbox_restart_worker.py tests/test_ai_auto_reply_outbox_postgres_mvcc.py
git commit --only -m "测试：扩展 outbox 跨进程 PostgreSQL 入口" -- tests/helpers/outbox_restart_worker.py tests/test_ai_auto_reply_outbox_postgres_mvcc.py
```

Expected: 提交只含两份允许测试文件；三份治理计划仍保持暂存。

### Task 3: 建立专用 PostgreSQL 测试库预检与基础场景

**Files:**
- Modify: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`
- Test: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`

- [ ] **Step 1: 启动现有 dev PostgreSQL profile**

Run:

```powershell
docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
$pgUser = docker exec auto-wechat-postgres-dev printenv POSTGRES_USER
docker exec auto-wechat-postgres-dev pg_isready -U $pgUser -d postgres
```

Expected: PostgreSQL 容器 healthy；不得启动、停止或重建其他服务。

- [ ] **Step 2: 幂等创建固定专用测试库**

Run:

```powershell
$pgUser = docker exec auto-wechat-postgres-dev printenv POSTGRES_USER
$exists = docker exec auto-wechat-postgres-dev psql -U $pgUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='auto_wechat_outbox_test'"
if (-not ($exists -match '1')) { docker exec auto-wechat-postgres-dev createdb -U $pgUser -O auto_wechat auto_wechat_outbox_test }
$env:SMOKE_DATABASE_URL = 'postgresql+psycopg://auto_wechat:change_me@127.0.0.1:5432/auto_wechat_outbox_test'
```

Expected: 只创建/复用 `auto_wechat_outbox_test`；不删除数据库。

- [ ] **Step 3: 用 Alembic 初始化到 head**

Run:

```powershell
$env:DATABASE_URL = $env:SMOKE_DATABASE_URL
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head
python -m alembic -c migrations/postgres/auto_wechat/alembic.ini current
Remove-Item Env:DATABASE_URL
```

Expected: current 输出 `0016 (head)`；不得执行 ORM create_all。

- [ ] **Step 4: 写入 PostgreSQL fixture、精确清理和子进程 runner**

在新测试文件加入：

```python
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import time
import uuid

from sqlalchemy import bindparam, create_engine, inspect, text


def _pg_url() -> str:
    worker = _load_worker_module()
    raw = os.environ.get("SMOKE_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("SMOKE_DATABASE_URL 未设置，跳过真实 PostgreSQL 专项")
    return worker._validate_smoke_database_url(raw)


def _namespace() -> str:
    return uuid.uuid4().hex


def _worker_env(url: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key != "SMOKE_DATABASE_URL" and any(
            marker in key.upper()
            for marker in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
        ):
            env.pop(key)
    env.update({
        "SMOKE_DATABASE_URL": url,
        "AUTO_WECHAT_ENV_FILE": str(ROOT / "missing.env"),
        "APP_ENV": "development",
        "AI_AUTO_REPLY_OUTBOX_ENABLED": "false",
        "DOUYIN_AUTO_REPLY_ENABLED": "false",
        "DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED": "false",
        "PYTHONUNBUFFERED": "1",
    })
    env.pop("DATABASE_URL", None)
    return env


def _run_worker(
    tmp_path: Path,
    url: str,
    action: str,
    *,
    namespace: str,
    run_id: int | None = None,
    status: str | None = None,
    timing: str | None = None,
    with_sent_record: bool = False,
    lease_owner: str | None = None,
    expected_code: int = 0,
) -> dict:
    token = uuid.uuid4().hex
    command = [
        sys.executable,
        str(WORKER),
        "--postgres-smoke",
        "--namespace", namespace,
        "--log", str(tmp_path / f"worker-{token}.log"),
        "--audit", str(tmp_path / "audit.jsonl"),
        "--action", action,
    ]
    if run_id is not None:
        command.extend(("--run-id", str(run_id)))
    if status is not None:
        command.extend(("--status", status))
    if timing is not None:
        command.extend(("--timing", timing))
    if with_sent_record:
        command.append("--with-sent-record")
    if lease_owner is not None:
        command.extend(("--lease-owner", lease_owner))
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=_worker_env(url),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == expected_code, result.stderr
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines, result.stderr
    return json.loads(lines[-1])


def _cleanup_namespace(engine, namespace: str) -> None:
    merchant_id = f"outbox_pg_test_{namespace}"
    with engine.begin() as conn:
        run_ids = conn.execute(
            text("SELECT id FROM ai_auto_reply_runs WHERE merchant_id=:merchant_id"),
            {"merchant_id": merchant_id},
        ).scalars().all()
        if run_ids:
            delete_sends = text(
                "DELETE FROM douyin_private_message_sends "
                "WHERE auto_reply_run_id IN :run_ids"
            ).bindparams(bindparam("run_ids", expanding=True))
            conn.execute(delete_sends, {"run_ids": run_ids})
        conn.execute(
            text("DELETE FROM ai_auto_reply_runs WHERE merchant_id=:merchant_id"),
            {"merchant_id": merchant_id},
        )
        remaining_runs = conn.execute(
            text("SELECT count(*) FROM ai_auto_reply_runs WHERE merchant_id=:merchant_id"),
            {"merchant_id": merchant_id},
        ).scalar_one()
        assert remaining_runs == 0
        if run_ids:
            count_sends = text(
                "SELECT count(*) FROM douyin_private_message_sends "
                "WHERE auto_reply_run_id IN :run_ids"
            ).bindparams(bindparam("run_ids", expanding=True))
            assert conn.execute(count_sends, {"run_ids": run_ids}).scalar_one() == 0


def _namespace_snapshot(engine, namespace: str) -> dict:
    merchant_id = f"outbox_pg_test_{namespace}"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, status, attempt_count, lease_owner IS NOT NULL AS has_lease "
                "FROM ai_auto_reply_runs WHERE merchant_id=:merchant_id ORDER BY id"
            ),
            {"merchant_id": merchant_id},
        ).mappings().all()
    return {"namespace": namespace, "runs": [dict(row) for row in rows]}


@contextmanager
def _isolated_namespace(engine, namespace: str):
    try:
        yield
    except BaseException:
        try:
            print(
                json.dumps(_namespace_snapshot(engine, namespace), sort_keys=True, default=str),
                file=sys.stderr,
            )
        except Exception as snapshot_error:
            print(f"namespace snapshot failed: {type(snapshot_error).__name__}", file=sys.stderr)
        try:
            _cleanup_namespace(engine, namespace)
        except Exception as cleanup_error:
            print(f"namespace cleanup failed: {type(cleanup_error).__name__}", file=sys.stderr)
        raise
    else:
        _cleanup_namespace(engine, namespace)
```

- [ ] **Step 5: 实现 P2 schema 与 P3 提交可见性**

P2 必须用 `inspect(engine)` 断言列和索引：

```python
def test_p2_postgres_schema_is_alembic_0016_contract():
    engine = create_engine(_pg_url())
    try:
        columns = {item["name"]: item for item in inspect(engine).get_columns("ai_auto_reply_runs")}
        assert {"lease_owner", "lease_expires_at", "attempt_count", "next_attempt_at", "last_failure_stage"} <= columns.keys()
        assert columns["lease_expires_at"]["type"].timezone is True
        assert columns["next_attempt_at"]["type"].timezone is True
        indexes = {item["name"] for item in inspect(engine).get_indexes("ai_auto_reply_runs")}
        assert "idx_ai_auto_reply_runs_status_next_attempt" in indexes
        assert "idx_ai_auto_reply_runs_lease" in indexes
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0016"
    finally:
        engine.dispose()
```

P3 使用两个独立 Worker 动作 `seed` 与 `inspect`：

```python
def test_p3_new_process_reads_committed_pending_run(tmp_path):
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace)
            inspected = _run_worker(
                tmp_path,
                url,
                "inspect",
                namespace=namespace,
                run_id=seeded["run_id"],
            )
            assert seeded["pid"] != inspected["pid"]
            assert inspected["run_id"] == seeded["run_id"]
            assert inspected["status"] == "pending"
    finally:
        engine.dispose()
```

- [ ] **Step 6: 运行 P1-P3 且真实 PG 用例 0 skipped**

Run:

```powershell
python -m pytest tests/test_ai_auto_reply_outbox_postgres_mvcc.py -q -rs
```

Expected: P1-P3 全部 PASS，输出中不得出现 skip；连接目标只显示脱敏信息。

- [ ] **Step 7: 提交基础 PG 场景**

Run:

```powershell
git add -- tests/test_ai_auto_reply_outbox_postgres_mvcc.py
git commit --only -m "测试：覆盖 outbox PostgreSQL 基础恢复合同" -- tests/test_ai_auto_reply_outbox_postgres_mvcc.py
```

### Task 4: 完成 20 路 MVCC 竞争、恢复、对账和防覆盖

**Files:**
- Modify: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`
- Test: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`

- [ ] **Step 1: 实现 20 子进程文件门禁 runner**

实现 `_run_claim_race()`：

```python
def _run_claim_race(tmp_path: Path, url: str, namespace: str, workers: int = 20):
    tmp_path.mkdir(parents=True, exist_ok=False)
    start_file = tmp_path / "start"
    processes = []
    ready_files = []
    try:
        for index in range(workers):
            ready = tmp_path / f"ready-{index}"
            ready_files.append(ready)
            process = subprocess.Popen(
                [
                    sys.executable, str(WORKER),
                    "--postgres-smoke",
                    "--namespace", namespace,
                    "--log", str(tmp_path / f"worker-{index}.log"),
                    "--audit", str(tmp_path / "audit.jsonl"),
                    "--action", "claim-once",
                    "--ready-file", str(ready),
                    "--start-file", str(start_file),
                ],
                cwd=ROOT,
                env=_worker_env(url),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            processes.append(process)
        deadline = time.monotonic() + 15
        while not all(path.exists() for path in ready_files):
            if time.monotonic() >= deadline:
                raise TimeoutError("20 路 claim ready gate timeout")
            time.sleep(0.02)
        start_file.write_text("start", encoding="utf-8")
        payloads = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            payloads.append(json.loads([line for line in stdout.splitlines() if line][-1]))
        return payloads
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
```

- [ ] **Step 2: 实现 P4 十轮单胜断言**

每轮使用独立门禁目录，只 seed 一个 pending run，执行 20 路竞争并断言：

```python
for round_index in range(10):
    namespace = _namespace()
    round_dir = tmp_path / f"round-{round_index}"
    with _isolated_namespace(engine, namespace):
        seeded = _run_worker(round_dir.parent, url, "seed", namespace=namespace)
        run_id = seeded["run_id"]
        payloads = _run_claim_race(round_dir, url, namespace)
        winners = [payload for payload in payloads if payload["run_ids"]]
        assert len(winners) == 1
        assert winners[0]["run_ids"] == [run_id]
        assert len({owner for payload in winners for owner in payload["lease_owners"]}) == 1
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT status, attempt_count, lease_owner FROM ai_auto_reply_runs "
                    "WHERE id=:run_id"
                ),
                {"run_id": run_id},
            ).mappings().one()
        assert row["status"] == "processing"
        assert row["attempt_count"] == 1
        assert row["lease_owner"]
```

每轮由 `_isolated_namespace` 精确清理；独立 `round_dir` 防止上一轮 start 文件令下一轮提前放行。

- [ ] **Step 3: 实现 P5 异常退出租约恢复**

复用 `claim-crash` 退出码 23。断言：

1. crash 后 status=processing 且租约非空。
2. 租约未过期时第二个 `claim-once` 返回空。
3. 父进程把 `lease_expires_at` 更新为 UTC 过去时间。
4. 安全 cycle 后 status=blocked、租约清空、审计 processed 精确 1 条且 `recovered_failure_stage=lease_expired`。
5. external_calls=0。

- [ ] **Step 4: 实现 P6 retry_wait 到期语义**

seed future retry_wait，第一次 cycle 断言仍为 retry_wait 且 processed=0；更新 `next_attempt_at` 为 UTC 过去时间后第二次 cycle 断言 blocked、processed=1、external_calls=0。

- [ ] **Step 5: 实现 P7 send_authorized 双分支**

使用参数化 `with_sent_record=True/False`：

```python
@pytest.mark.parametrize(
    ("with_sent_record", "expected_status", "expected_failure_stage"),
    [
        (True, "sent", None),
        (False, "send_unknown", "send_authorized_crash_unknown"),
    ],
)
def test_p7_send_authorized_reconciliation(
    tmp_path,
    with_sent_record,
    expected_status,
    expected_failure_stage,
):
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(
                tmp_path,
                url,
                "seed",
                namespace=namespace,
                status="send_authorized",
                timing="expired",
                with_sent_record=with_sent_record,
            )
            cycled = _run_worker(tmp_path, url, "cycle", namespace=namespace)
            assert cycled["external_calls"] == 0
            assert cycled["processed_count"] == 0
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT status, lease_owner, lease_expires_at, last_failure_stage "
                        "FROM ai_auto_reply_runs WHERE id=:run_id"
                    ),
                    {"run_id": seeded["run_id"]},
                ).mappings().one()
            assert row["status"] == expected_status
            assert row["lease_owner"] is None
            assert row["lease_expires_at"] is None
            assert row["last_failure_stage"] == expected_failure_stage
    finally:
        engine.dispose()
```

两分支均断言 lease_owner/lease_expires_at 为 None、processed 审计为空、external_calls=0；只有 True 分支允许存在 1 条显式预置 sent 流水。

- [ ] **Step 6: 实现 P8 旧 Worker 防覆盖**

使用父进程 SQLAlchemy Session 和全新 Worker 子进程：

1. seed processing，owner=`old-owner`，租约未过期。
2. Session B 原子更新为 `new-owner` 与新的未过期租约并提交。
3. 全新 Worker 执行 `guarded-block-once --run-id <id> --lease-owner old-owner`，内部调用真实 `_guarded_lease_update(expected_status="processing")`。
4. 断言子进程输出 rowcount=0；数据库仍为 new-owner、新租约和新 Worker 写入的诊断值。
5. finally 关闭 Session 并精确清理 namespace。

- [ ] **Step 7: 实现 P9 外部副作用总断言**

所有调用安全 cycle 的 helper 已强制 `external_calls==0`。本测试再按 namespace 查询：

- 非 P7 预置场景发送流水必须为 0。
- P7 True 场景只能有 1 条预置 sent 流水。
- audit 只允许 `processed`，不得出现发送事件。
- 失败信息不得包含 `change_me`、原始 URL 或任何连接凭据；专用 PostgreSQL 数据库连接不计入业务外部调用。

- [ ] **Step 8: 运行专项与十轮稳定性**

Run:

```powershell
python -m pytest tests/test_ai_auto_reply_outbox_postgres_mvcc.py -q -rs
1..10 | ForEach-Object { python -m pytest tests/test_ai_auto_reply_outbox_postgres_mvcc.py -q --tb=short; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
```

Expected: P1-P9 全 PASS，十轮全 PASS，0 skipped、0 timeout、0 duplicate claim、0 遗留子进程。

- [ ] **Step 9: 提交完整 PostgreSQL/MVCC 证据**

Run:

```powershell
git add -- tests/test_ai_auto_reply_outbox_postgres_mvcc.py
git commit --only -m "测试：固化 outbox PostgreSQL MVCC 恢复证据" -- tests/test_ai_auto_reply_outbox_postgres_mvcc.py
```

### Task 5: 完整回归、基线对照与候选冻结

**Files:**
- Test: `tests/helpers/outbox_restart_worker.py`
- Test: `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`
- Test: `tests/test_ai_auto_reply_outbox_restart_recovery.py`
- Test: `tests/test_ai_auto_reply_outbox_service.py`
- Test: `tests/test_ai_auto_reply_send_service.py`
- Test: `tests/test_ai_auto_reply_dry_run.py`
- Test: `tests/test_douyin_webhook.py`
- Test: `tests/test_douyin_webhook_atomic_idempotency.py`

- [ ] **Step 1: 执行编译与差异检查**

Run:

```powershell
python -m py_compile tests/helpers/outbox_restart_worker.py tests/test_ai_auto_reply_outbox_postgres_mvcc.py
git diff --check 70f3e22b175e415ec6b1824e1e8f2e6a0a96ea6d..HEAD
git diff --name-status 70f3e22b175e415ec6b1824e1e8f2e6a0a96ea6d..HEAD
```

Expected: 编译通过；diff check 干净；实现增量仅两份允许测试文件。

- [ ] **Step 2: 执行 PostgreSQL 与 SQLite 专项**

Run:

```powershell
python -m pytest tests/test_ai_auto_reply_outbox_postgres_mvcc.py -q -rs
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
```

Expected: PostgreSQL P1-P9 0 failed/0 skipped；SQLite 11 passed/0 failed。

- [ ] **Step 3: 执行相邻状态机与 webhook 回归**

Run:

```powershell
python -m pytest tests/test_ai_auto_reply_outbox_service.py tests/test_ai_auto_reply_send_service.py tests/test_ai_auto_reply_dry_run.py -q
python -m pytest tests/test_douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py -q
```

Expected: Candidate 0 个新增失败。任何失败必须在 `70f3e22` 快照用同命令、同环境对照；禁止仅凭历史报告判为基线。

- [ ] **Step 4: 核对候选线性与治理文件**

Run:

```powershell
git merge-base --is-ancestor 70f3e22b175e415ec6b1824e1e8f2e6a0a96ea6d HEAD
git rev-list --parents 70f3e22b175e415ec6b1824e1e8f2e6a0a96ea6d..HEAD
git status --short
```

Expected: 全部单父线性；工作区只保留三份治理计划暂存；无测试残留文件。

- [ ] **Step 5: 回传候选，不推送**

报告必须包含：

- Integration-Base、Approved-Spec-Head、Implementation-Base、Candidate 完整哈希。
- 实现增量与最终集成范围的 name-status。
- P1-P9 逐项证据、20 路竞争十轮统计、PID/退出码/租约/rowcount/清理证据。
- PostgreSQL server 版本、Alembic revision=0016，只允许脱敏连接信息。
- SQLite 专项与相邻回归结果、Base/Candidate 对照的范围外基线。
- business external_calls=0、非数据库 socket=0、非预置发送流水=0、测试 namespace 残留=0、遗留子进程=0；专用 PostgreSQL 数据库连接是唯一允许的网络传输。
- 未连接 staging/production，未部署、未迁移生产、未真实发送。
- 文档影响：实现候选不改活动文档；独立测试通过并推送后，另起文档闭环更新 `05_PROJECT_CONTEXT.md`、`12_TEST_PLAN_AUTO_WECHAT.md` 与当前已过期的 `POSTGRESQL_MIGRATION_NOTES.md` outbox 0016 状态。

输出：

```text
CANDIDATE_READY <完整哈希>
```

禁止自行发出 `TEST_REQUEST`、`APPROVE_TEST`、推送、部署或发布。
