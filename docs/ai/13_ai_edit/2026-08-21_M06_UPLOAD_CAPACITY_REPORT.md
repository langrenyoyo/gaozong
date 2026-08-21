# UPLOAD_CAPACITY_REPORT（P0.5-M06-UPLOAD-CAPACITY-CHECK-1）

> 状态：CHECK_COMPLETE（仅只读检查，未修改代码/配置/部署）
> 角色：Exploration / Capacity Authority
> 范围：确认当前 9000 对大文件上传（`POST /api/ai-edit/materials/upload-tos`，M06 AI 剪辑素材链路）的承载风险
> 检查日期：2026-08-21
> 方式：生产 SSH 只读核实（`ssh xg-prod`）+ 代码核对

## FACTS

### 1. API 容器 memory 限制（生产实测）

```text
docker inspect xg-auto-wechat-api
  Memory=0  NanoCpus=0  CpuQuota=0  CpuPeriod=0  CpuShares=0  MemorySwap=0
```

**结论：9000 容器无任何内存/CPU 资源限制**（未设置 cgroup 限额），可占用宿主机全部可用资源。无容器级内存上限 → 大文件上传不受容器 OOM 保护，一旦内存耗尽由宿主机 Linux OOM killer 全局裁决（不保证杀 9000 容器，可能波及同宿主其它容器）。

### 2. CPU 限制

- 容器无 CPU 限制（NanoCpus=0 / CpuQuota=0）。
- 宿主机 **16 核**（`nproc`=16）。
- 上传主路径为同步 `def` 路由（threadpool 执行），非 CPU 密集，CPU 不是上传瓶颈。

### 3. uvicorn worker 数量

```text
容器 Cmd: ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","9000"]
```

**无 `--workers` 参数 → 默认单 worker 单进程**（uvicorn 默认 1 worker）。

并发模型：`upload_material_to_tos` 为**同步 `def`**（[ai_edit.py:300](app/routers/ai_edit.py#L300)），FastAPI 放入 **threadpool（anyio 默认上限 40 线程）** 执行 → **多个并发上传请求真正并行执行**，内存随并发数线性累加（不是单线程串行）。

### 4. 上传代码是否全量 read（确认）

```python
# ai_edit.py:330-333
content = file.file.read()              # ← 全量整读，内存峰值在此
max_size = 500 * 1024 * 1024
if len(content) > max_size:             # ← 大小检查在整读之后
    raise HTTPException(413, FILE_TOO_LARGE)
```

- **确认全量 `read()`**：整个文件读入 Python bytes（500MB 文件 ≈ 500MB 内存）。
- Starlette `UploadFile` 底层为 `SpooledTemporaryFile`（默认 >1MB 落盘到临时文件），故**接收阶段不占大内存**（body 落盘），内存峰值集中在 `read()` 一步。
- 大小检查在整读**之后**：>500MB 文件会先白读 N MB 进内存（=文件大小，甚至 >500MB）才返回 413。
- TOS 上传（`put_object(Body=f)`）为**流式**，不额外占内存；`probe_video`（ffprobe 子进程）不占主进程内存。
- 磁盘侧：nginx 缓冲临时文件 + Starlette spool 临时文件 + `tmp_path` 写盘，峰值约 3×500MB 磁盘（`/` 盘可用 301G，充足）。

### 5. 生产 500MB 上传内存风险测算

**实测基线**：
```text
9000 进程 RSS: 279,644 KB ≈ 273 MiB（docker stats 同源 246-273MiB）
宿主机: total 30GiB / used 4.7GiB / available ~26GiB / Swap 0B / 16 核
同宿主其它容器（used-car/knowledge-train/car-project 等 15 个）: 合计 ~1.2GiB
OOM 历史: OOMKilled=false / RestartCount=0（从未发生 OOM）
```

**单次 500MB 上传内存峰值**：
```text
≈ 273MiB（基线） + 500MiB（content bytes） ≈ 773MiB/请求
```

**并发风险矩阵**（threadpool 真正并行，N 个并发 × 500MB）：

| 并发 500MB 上传数 | 峰值内存 | 相对宿主机 available 26GiB | 风险 |
|---|---|---|---|
| 1 | ~0.77 GiB | 3% | 无 |
| 5 | ~2.7 GiB | 10% | 无 |
| 10 | ~5.2 GiB | 20% | 低 |
| 20 | ~10.2 GiB | 39% | 中（需 20 个并发才达，业务可能性低） |
| 40（threadpool 上限） | ~20.2 GiB | 78% | 高（理论触顶，实际几乎不可能） |

**实际并发约束**：前端 `runUpload` 为**逐文件顺序上传**（for 循环 await，[uploadFeedback.ts:96-114](frontend/src/features/ai-edit/uploadFeedback.ts#L96-L114)），单个浏览器标签页并发=1；并发仅来自**多用户 / 多标签页**同时上传。前端 `multiple` 多选也不会并发。

## RISK 结论

| # | 风险 | 等级 | 依据 |
|---|---|---|---|
| R1 | 单次/低并发 500MB 上传内存超限 | **低（当前无风险）** | 峰值 ~773MB，远低于宿主机 26GiB available；从未 OOM |
| R2 | 高并发大文件上传内存线性累加 | **中（理论）** | threadpool 40 线程真正并行，需 ≥20 个并发 500MB 才逼近 50% 内存；业务实际不可能 |
| R3 | 容器无内存限制 + 无 Swap | **中（结构性）** | 一旦触顶由宿主机 OOM killer 全局裁决，可能波及同宿主其它容器（used-car 等 15 个）；无 Swap 无缓冲 |
| R4 | `read()` 整读内存 + 检查后置 | **中（设计缺陷）** | >500MB 文件先白读（内存峰值=文件大小）才 413；非流式 |
| R5 | 与 nginx 1000m 不一致 | **低** | 500MB 后端限制 < 1000m nginx，>500MB 文件会完整传到后端才拒绝 |

**总体判断**：当前承载能力**充足**——单次 500MB 上传内存峰值 ~0.77GiB，宿主机 26GiB available、从未 OOM，实际业务并发（单标签页顺序上传）不会触发内存瓶颈。风险集中在**结构性弱点**（无容器限制、无 Swap、整读非流式），在「多用户同时上传大文件 + 未来上传上限上调 + 增加 uvicorn worker」三者叠加时才会放大。

## IMPACT_SCOPE

- **当前影响**：无（承载能力充足，未发生 OOM；413 事故根因是 nginx 50m 而非内存，已由 1000m 缓解）。
- **潜在影响面**：仅 M06 素材上传接口；多并发大文件上传时可放大为内存压力，进而影响同宿主其它容器（无隔离）。
- **禁止修改**：代码 / 配置 / nginx / 部署 / 数据库——本任务只读，全部未改。

## WAITING_FOR_DECISION

1. 是否将「后端 `read()` 整读 + 检查后置」列为稳定性修复项（流式边读边限，消除内存峰值）？
2. 是否评估为 9000 容器设置内存上限（如 4GiB）以隔离 OOM 波及面？——涉及部署配置，需独立审批。
3. 是否需要在多 worker 化（uvicorn `--workers`）时同步评估上传内存叠加？——当前单 worker 不涉及。

---
TASK_STATUS: CHECK_COMPLETE
CODE_CHANGE=0 / DB_CHANGE=0 / MIGRATION=0 / DEPLOYMENT=0 / COMMIT=0
（仅 SSH 只读核实容器资源/进程/日志）
