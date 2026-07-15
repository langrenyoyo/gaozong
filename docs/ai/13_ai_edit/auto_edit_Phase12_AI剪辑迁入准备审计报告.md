# auto_edit Phase 12 AI剪辑迁入准备审计报告

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 审计日期 | 2026-07-14 |
| 来源项目 | `E:\work\project\auto_edit` |
| 来源基线 | `develop@d0c81895f770090d5853952478b165d19a53bfab` |
| 目标项目 | `E:\work\project\auto_wechat` |
| 目标阶段 | Phase 12 小高素材库与 AI 小高剪辑本地 MVP |
| 审计方式 | 只读源码审计、调用链追踪、离线测试、目标项目承接能力对照 |
| 文档状态 | 迁入能力证据基线；当前产品和架构边界见 `2026-07-15_Phase12_AI剪辑本地MVP设计.md` |

## 2. 阶段目标与边界

### 2.1 本阶段目标

本报告负责明确 `auto_edit` 哪些内容值得迁、迁到哪里、迁入前必须修什么，以及 `auto_wechat` 需要提供什么运行边界。2026-07-15 已批准 Phase 12 本地 MVP：正式实现将在本仓库逐任务迁入，但仍禁止整体复制和外部仓库运行时依赖。

### 2.2 本阶段允许范围

1. 审计 `auto_edit` 的真实入口、模块、数据流和测试。
2. 对照 `auto_wechat` 已有任务壳、产物壳和可复用的安全模式。
3. 给出迁入分层、数据契约和验收门槛。
4. 为已批准的本地 MVP 逐任务执行包提供源码证据。

### 2.3 本阶段禁止事项

1. 不整体复制 `auto_edit/src`、`scripts` 或 `runs` 到本仓库。
2. 不迁入开发 runner、本地 JSON 任务库、样片专用默认策略和外部绝对路径协议。
3. 日常自动测试不调用真实 LLM，不下载真实视觉模型。
4. 不把外部 `E:\work\project\auto_edit` 作为运行时依赖。
5. 不把已被客户取消的一键过审混入 AI剪辑迁入范围。

### 2.4 本阶段验收标准

1. 能说明正式入口当前能做什么、不能做什么。
2. 可复用内容分为“直接迁移候选、适配后迁移、禁止原样迁入”。
3. 已确认阻断项有源码证据和处理建议。
4. 明确 BrollStudio 增稳与素材区间如何接入。
5. 给出正式迁入专项的顺序和每阶段退出门槛。

## 3. 结论摘要

### 3.1 迁入判定

结论为：**有条件迁入，禁止整体复制。**

`auto_edit` 已经具备一套较完整的二手车营销视频剪辑内核，主要包括：

- FunASR 转写适配。
- 场景切分、OpenCV 画质分析、YOLO 标签、open_clip 图文匹配。
- 候选片段和多素材规划。
- 参考样片结构规划、LLM 结构化输出解析与校验。
- FFmpeg 裁切、拼接、画面替换。
- 基础字幕、动态高亮字幕、字幕烧录。
- BGM 混音和质量报告。
- 大量纯逻辑规则、校验器和离线测试。

但它当前仍是本地脚本驱动的验证项目，不是可直接挂到 9000 的生产服务。正式迁入应保留经过验证的剪辑内核，重写任务、存储、权限、Worker 和运行编排边界。

### 3.2 最重要的事实

1. 正式客户入口仍要求外部提供 `--candidate-segments` 和 `--reference-script`。
2. `--skip-asr` 只有参数声明，没有自动 ASR 主链可供跳过。
3. ASR、视觉分析、候选生成能力确实存在，但没有接入正式客户入口。
4. 主流程依赖多个 Python 子脚本和 `subprocess.run()`，没有超时、取消、租约、阶段心跳或可靠恢复。
5. 真实画面替换只执行低风险 `replace`，`insert_broll` 和 `overlay_broll` 仍不执行。
6. `auto_edit` 没有视频增稳实现；视频增稳继续复用 BrollStudio，而不是在 `auto_edit` 中寻找不存在的代码。
7. `auto_wechat` 目前只有 `AiEditJob`、`AiEditJobArtifact` 数据壳，没有正式路由、Worker、上传、下载、取消和事件实现。

### 3.3 推荐目标

```text
React（与小高AI微信助手同机）
  -> 9000：鉴权、auto_wechat:ai_edit、可信商户 metadata、任务与审计
  -> 127.0.0.1:19000：本地素材、队列和子进程监管
  -> 随包 ai_edit_worker.exe：ASR、分析、增稳、规划输入、渲染和媒体校验
  -> 9000：只保存 metadata、缩略图和用户主动上传的云端产物
```

9000 和 19000 主进程都不能同步执行 ASR、模型推理或 FFmpeg 长任务。重型处理固定在 Python 3.11 剪辑子进程中执行。

## 4. 审计基线与规模

### 4.1 仓库状态

- 分支：`develop`。
- 提交：`d0c81895f770090d5853952478b165d19a53bfab`。
- 审计时工作区：干净。
- Python 要求：`>=3.11`，见 `pyproject.toml`。

### 4.2 代码规模

审计范围共 195 个 Python/测试脚本文件：

| 分类 | 数量 |
|---|---:|
| `src` 源码文件 | 65 |
| `scripts` 脚本文件 | 39 |
| `tests` 测试文件 | 91 |
| 合计 | 195 |

总代码和测试规模约 5 万行。该规模不适合以一次性目录复制完成迁入。

### 4.3 权属前置风险

仓库根目录未发现项目级 `LICENSE`、`LICENCE`、`COPYING` 或 `NOTICE`。正式复制源码前必须确认：

1. `auto_edit` 业务源码的所有权和内部迁入授权。
2. FFmpeg、FunASR、YOLO、open_clip、PyTorch 等组件的分发与模型许可证要求。
3. 模型权重能否随部署镜像交付，还是只能在受控运行环境拉取。

本文只记录工程风险，不构成法律意见。

## 5. 当前真实处理流程

### 5.1 正式客户入口

正式入口为：

```text
scripts/run_client_material_pipeline.py
```

其当前真实流程是：

```text
已有素材文件
  + 外部 candidate_segments.json
  + 外部 reference_script.md
  -> 输入预检
  -> 参考结构 LLM 规划
  -> 画面覆盖补全
  -> 可选 FFmpeg 预览渲染
  -> 可选画面替换计划消费
  -> 可选画面替换 dry-run
  -> 可选真实 replace
  -> 可选基础/动态字幕生成与烧录
  -> 可选 BGM 混音
  -> 汇总元数据、状态和报告
```

关键证据：

- `scripts/run_client_material_pipeline.py:186-202` 强制检查参考脚本和候选片段。
- `scripts/run_client_material_pipeline.py:198` 明确写出“ASR 到 judge 的自动前半链路将在后续阶段补齐”。
- `scripts/run_client_material_pipeline.py:476-574` 只构建参考规划、画面覆盖和可选渲染步骤。
- `scripts/run_client_material_pipeline.py:313-328` 虽声明 `--skip-asr`，后续没有消费该参数。

因此，当前正式入口不是“上传原始素材后自动一键成片”的完整入口。

### 5.2 已存在但未接入正式入口的前半段

前半段能力并非完全缺失：

| 能力 | 真实实现 |
|---|---|
| 单素材音频提取与 FunASR 转写 | `src/auto_edit/transcription.py` |
| 单素材场景切分和视觉分析 | `src/auto_edit/visual_analysis.py` |
| 多素材候选片段与规划 | `src/auto_edit/multi_planner.py` |
| 参考样片逻辑链解析 | `src/auto_edit/reference_script.py` |
| 临时串联验证 | `scripts/dev/run_fourth_client_001_full_once.py` |

临时 runner 的串联顺序为：

```text
原始视频
  -> ASR
  -> 视觉分析
  -> 从 transcript 临时构造 candidates
  -> 从 transcript 临时构造 reference script
  -> 调用正式客户入口
```

该 runner 位于 `scripts/dev`，并且代码说明其参考脚本只是临时结构输入，不能作为生产入口。

### 5.3 当前输入和输出

当前输入主要是本地绝对路径：

- 原始素材目录或文件列表。
- 候选片段 JSON。
- 参考脚本 Markdown。
- 可选 BGM、本地 sidecar 和多个校验报告。

当前输出主要落到本地 `output_dir`：

- 资产清单、规划 JSON 和 Markdown 报告。
- `final_video.mp4`、字幕视频、BGM 成片。
- 命令 stdout/stderr 和流水线状态。
- LLM 原始响应及解析失败报告。

这些本地路径只能作为迁入 Worker 的任务级临时目录，不能直接成为前端或数据库契约。

## 6. 复用矩阵

### 6.1 可作为首批直接迁移候选的纯逻辑

“直接迁移候选”仍要求更换包路径并补目标仓库测试，不表示逐文件无审查复制。

| 能力 | 主要文件 | 复用建议 |
|---|---|---|
| 数据模型和时间边界校验 | `models.py`、`time_boundary.py` | 优先迁入纯模型和边界规则 |
| 通用剪辑语法 | `edit_grammar.py` | 可迁通用语法，保留“台词只来自真实 ASR”约束 |
| LLM JSON 提取和 schema 校验 | `llm_client.py`、各 validator | 复用解析和失败语义，不复用密钥读取边界 |
| 参考脚本解析器 | `reference_script.py` | 复用解析器，不把路虎样片默认值作为全局策略 |
| 画面替换计划校验 | `visual_replacement_plan_validator.py` | 复用受控枚举、人工复核和风险阻断语义 |
| 质量过滤与重复检测 | `edit_quality_filter.py` | 拆出通用规则后迁，样片专用规则版本化 |
| 字幕分段和高亮规则 | `subtitle_*` 中纯函数 | 与渲染器分离后迁入 |
| 预检和报告结构 | `pipeline_preflight.py`、`preview_summary.py` | 复用结构，路径和存储输入改为受控对象 |
| 素材标签 sidecar 归一化 | `material_semantic_tag_sidecar.py` | 作为 BrollStudio 契约适配起点 |

### 6.2 必须适配后迁移的运行模块

| 能力 | 当前实现 | 必须完成的适配 |
|---|---|---|
| ASR | `transcription.py` | Worker 模型缓存、取消、超时、模型目录和资源限制 |
| 视觉分析 | `visual_analysis.py`、`adapters/vision.py` | 模型只加载一次、离线权重、GPU/CPU 配置、失败降级 |
| 多素材规划 | `multi_planner.py`、`reference_style_planner.py` | 输入契约、Prompt 版本、商户配置、可恢复阶段 |
| FFmpeg 渲染 | `renderer.py`、`multi_renderer.py`、`llm_render_bridge.py` | 统一子进程执行器、取消、超时、进度和产物强校验 |
| 画面替换 | `visual_replacement_execution.py` | 修复时间线、支持素材区间、统一决策与执行能力 |
| 字幕烧录 | `subtitle_burn_in.py`、`subtitle_dynamic_highlight.py` | 分辨率适配、字体打包和字体预检 |
| BGM | `bgm_packaging.py` | 音量标准、版权来源、时长和音频完整性校验 |
| LLM 客户端 | `llm_client.py` | 统一项目配置、算力计量、重试、脱敏和调用审计 |
| 总编排 | `run_client_material_pipeline.py` | 改为进程内服务调用和持久化阶段机，不继续脚本套脚本 |

### 6.3 不应原样迁入

| 内容 | 原因 |
|---|---|
| `dealer_task_store.py` | 本地 JSON 文件库，无商户隔离、数据库事务、并发控制和原子写 |
| `scripts/dev/` | 临时验收 runner，包含降级和样片专用假设 |
| `runs/`、样本、历史报告 | 运行产物和验收证据，不是产品源码 |
| 本地绝对路径适配 | 与 `storage_key`、多 Worker 和跨机器部署冲突 |
| 正式入口的 `subprocess` 脚本编排 | 无超时、取消、心跳和可靠恢复 |
| 路虎样片默认逻辑链 | 只能作为版本化商户模板，不能作为全局默认 |
| `.env`、模型缓存和本地权重 | 禁止复制环境秘密和机器状态 |

## 7. 已确认缺陷与迁入阻断项

### 7.1 正式入口缺少一键成片前半链路 - HIGH

正式入口要求调用方先准备候选片段和参考脚本。虽然 ASR、视觉分析和候选生成模块存在，但没有产品编排将它们串起。

处理要求：正式迁入专项必须先定义“原始素材 -> 候选片段”的稳定契约，不能用开发 runner 顶替。

### 7.2 子进程编排不适合生产 Worker - HIGH

`run_client_material_pipeline.py:1676-1677` 直接使用：

```python
subprocess.run(command, capture_output=True, text=True, check=False)
```

当前缺少：

- 超时。
- 取消与进程树终止。
- 阶段心跳和进度回写。
- 标准化错误码。
- stdout/stderr 限长和脱敏。
- Worker 崩溃后的租约回收。

处理要求：迁入后统一使用一个可取消的子进程执行器；Python 模块间优先进程内调用，只有 FFmpeg 等外部工具使用子进程。

### 7.3 `--reuse-existing` 会复用陈旧产物 - HIGH

`scripts/run_client_material_pipeline.py:577-581` 只判断声明的输出文件是否存在，没有校验：

- 输入文件 SHA-256。
- 输入参数摘要。
- Prompt 版本。
- 引擎版本。
- 模型版本。
- 产物大小、哈希和可探测性。

处理要求：正式任务使用输入指纹和版本化产物，不允许仅凭文件存在跳过阶段。

### 7.4 输入格式支持前后不一致 - HIGH

预检和入口允许 `.mp4`、`.mov`、`.m4v`、`.avi`、`.mkv`，但渲染桥只扫描 MP4：

- `scripts/run_client_material_pipeline.py:57`
- `scripts/render_llm_editing_preview.py:98-99`
- `src/auto_edit/llm_render_bridge.py:445-446`

处理要求：统一资产清单驱动渲染，不允许渲染阶段重新按扩展名扫描目录。

### 7.5 Broll sidecar 未进入真实执行 - HIGH

`material_semantic_sidecar` 当前用于计划消费和 dry-run，但真实执行仍从输入素材 inventory 重建候选：

- `scripts/run_client_material_pipeline.py:990-1028`
- `scripts/run_client_material_pipeline.py:1038-1076`

因此 sidecar 中的独立空镜候选不会稳定进入真实替换。

处理要求：真实执行必须消费同一份已校验候选快照，并钉住 `artifact_id + sha256 + usable_range`。

### 7.6 画面替换不支持 BrollStudio 可用区间 - HIGH

`material_semantic_tag_sidecar.py` 当前候选只有整文件 `path`、`duration`、`resolution`、标签和质量字段，没有空镜可用区间的起止时间。

处理要求：候选契约增加 `source_start`、`source_end`，并校验区间属于已审核的可用区间。

### 7.7 后段替换可能冻结候选尾帧 - HIGH

`visual_replacement_execution.py:228-232` 对候选执行：

```text
trim=duration=...
setpts=PTS-STARTPTS
overlay=enable='between(t,start,end)'
```

候选时间戳从 0 开始，但 overlay 可能在主视频后段才启用。默认 overlay 的次输入结束行为可能让后段显示候选尾帧，而不是从候选首帧播放。

处理要求：候选 PTS 必须偏移到目标 `timeline_start`，并显式设置 EOF 行为；增加非 0 秒时间线的真实 FFmpeg 回归测试。

### 7.8 计划枚举和真实执行能力不一致 - HIGH

校验器接受：

- `replace`
- `insert_broll`
- `overlay_broll`

但执行器在 `visual_replacement_execution.py:178-179` 只接受 `replace`，其余返回 `unsupported_decision`。

处理要求：一期要么从正式契约移除未实现决策，要么实现并通过真实时间线测试；不能继续“计划成功、执行降级”。

### 7.9 输出校验字段存在，但未形成强门禁 - HIGH

执行报告记录了 `duration_before/after`、`resolution_before/after`、音频和哈希，但成功路径只明确阻断“输入有音频而输出无音频”。当前没有强制：

- 输出时长与输入时长在容差内。
- 分辨率与目标一致。
- 帧率和时间戳稳定。
- 字幕时间不漂移。
- 替换区间之外画面不变。

处理要求：发布 artifact 前集中执行媒体探测和质量门禁，失败产物不得注册为可下载。

### 7.10 临时完整 runner 的视觉标签读取错误 - MEDIUM

`scripts/dev/run_fourth_client_001_full_once.py:503-510` 从 `visual_report.json` 顶层读取 `visual_tags` 或 `asset_visual_tags`。

但 `visual_analysis.py:223-234` 写出的 `visual_report.json` 顶层只有 `asset_id`、`source_path` 和 `scenes`，标签位于场景中。因此即使视觉分析成功，临时 runner 也可能回退到 `车辆外观`。

处理要求：该 runner 不迁入；正式契约直接消费结构化场景或 `.visual.json`。

### 7.11 视觉模型会按场景重复加载 - HIGH

`visual_analysis.py:349-373` 每次标签或评分调用都会新建检测器/评分器；`adapters/vision.py:168-232` 又在 `detect()` 和 `score()` 内加载 YOLO/open_clip 模型。

由于分析按场景循环，这会重复加载甚至触发权重下载，带来严重时延、内存和网络风险。

处理要求：模型实例由 Worker 进程级缓存持有；启动时预热和验证权重，任务处理中禁止隐式下载。

### 7.12 字幕分辨率和字体依赖固定 - MEDIUM

- 动态字幕固定 `PLAY_RES_X=720`、`PLAY_RES_Y=1280`。
- 基础字幕使用 `Microsoft YaHei`。
- 动态字幕使用 `宋体`。

处理要求：字幕坐标按目标画布计算；随包剪辑 Worker 安装并预检确定的中文字体，不依赖宿主机字体名称碰运气。

### 7.13 LLM 原始响应存在泄露风险 - HIGH

`llm_client.py:495-510` 在解析失败时写完整 `*_llm_raw_response.txt`。其他 smoke 和多模态索引模块也会写原始响应。

原始响应可能包含素材台词、客户业务信息和模型内部错误内容。

处理要求：

1. 原始响应只能进入受控诊断存储。
2. 不注册为普通 artifact，不向商户前端返回。
3. 设置保留期、访问权限和日志脱敏。
4. API 只返回稳定错误码和安全摘要。

### 7.14 本地任务库不能用于多租户 - HIGH

`dealer_task_store.py` 将 `task_id` 直接拼到目录路径，并直接 `write_text()` 更新任务和索引。它没有：

- 路径段白名单或根目录越界校验。
- 商户隔离。
- 文件锁或数据库事务。
- 原子替换。
- 版本条件更新。
- 并发领取和崩溃恢复。
- `cancel_requested/cancelled` 状态。

处理要求：只参考状态命名，不迁文件任务实现。

### 7.15 样片专用规则不能作为全局默认 - HIGH

`reference_script.DEFAULT_BEATS`、`material_coverage_audit.py` 和部分质量规则直接包含路虎、揽胜、川虎之家、车雷达、三年九万公里等样片内容。

虽然 `edit_grammar.py` 已引入通用营销语法，但旧规则仍会参与部分路径。

处理要求：

- 通用规则作为基础策略。
- 样片逻辑作为显式版本化模板。
- 商户未选择模板时禁止自动套用路虎专用事实或结构。

### 7.16 部分错误信息源码已乱码 - MEDIUM

`run_client_material_pipeline.py` 的候选素材解析路径存在已损坏的中文错误字符串，例如目录不存在和无可用 `asset_id` 的提示。

处理要求：迁移模块时修复为稳定错误码和中文安全文案，不复制乱码文本。

### 7.17 当前没有视频增稳实现 - FACT

在 `auto_edit` 源码和脚本中未发现 Vid.Stab、光流稳像或其他视频增稳处理。视频增稳能力来自已单独评估的 BrollStudio：

```text
docs/ai/13_ai_edit/BrollStudio_空镜素材复用与视频增稳评估报告.md
```

## 8. BrollStudio 与 auto_edit 的连接方式

### 8.1 职责划分

```text
BrollStudio
  = 空镜导入、SHA-256、增稳、多模态标注、可用区间、人工复核

auto_edit 迁入内核
  = 口播 ASR、候选生成、结构规划、素材匹配、时间线、字幕、BGM、成片
```

BrollStudio 不负责一键成片，`auto_edit` 也不应重复实现已有的增稳与素材复核能力。

### 8.2 推荐内部候选契约

以下是 9000/Worker 内部契约，不是前端可直接提交的可信字段：

```json
{
  "schema_version": "ai_edit_material_candidate_v1",
  "material_id": "mat_xxx",
  "artifact_id": "artifact_xxx",
  "source_sha256": "...",
  "duration_seconds": 12.34,
  "width": 1080,
  "height": 1920,
  "fps": 30.0,
  "stabilization_status": "completed",
  "review_status": "approved",
  "tags": ["showroom_wide", "car_exterior"],
  "quality_flags": [],
  "usable_ranges": [
    {
      "source_start": 2.4,
      "source_end": 8.7,
      "stability_score": 0.91,
      "tags": ["showroom_wide"]
    }
  ]
}
```

`merchant_id` 从 9000 的可信鉴权上下文和 Local Agent 鉴权映射取得，不能接受前端自报。19000 由素材 ID 解析本地受管相对路径；云端素材再由 artifact ID 解析内部 `storage_key`，前端不接触底层路径。

### 8.3 连接规则

1. 只消费 `stabilization_status=completed` 且 `review_status=approved` 的区间。
2. 任务创建时钉住候选 artifact 的 SHA-256、大小和区间快照。
3. 真实渲染使用 `source_start/source_end`，不能把整段素材从 0 秒开始截取。
4. PostgreSQL 是素材 metadata 真源；本地受管文件是 `local_only` 媒体真源；不共享 BrollStudio SQLite 文件。
5. 底层素材允许内容去重，但商户资产、标签、审核和任务必须隔离。
6. BrollStudio 原片、增稳片和分析报告分别登记为受控素材或产物；默认留在本地，用户主动选择后才上传云端。

## 9. auto_wechat 当前承接差距

### 9.1 已有内容

`auto_wechat` 已有：

- `app/models.py:1303` 的 `AiEditJob`。
- `app/models.py:1324` 的 `AiEditJobArtifact`。
- SQLite 和 PostgreSQL 对应迁移壳。
- `app/schemas.py:2077` 的任务输出结构。
- `app/schemas.py:2089` 的产物输出结构。
- `auto_wechat:ai_edit` 入口权限约定。

### 9.2 尚未实现

当前尚无：

- `app/routers/ai_edit.py` 正式路由。
- 19000 AI剪辑协调层和随包 `ai_edit_worker.exe`。
- 任务原子领取、租约、心跳、取消和重试。
- 输入素材和长期素材库模型。
- 上传、预览和下载端点。
- 任务阶段事件和进度查询。
- FFmpeg、FunASR、视觉模型运行镜像。

### 9.3 现有任务壳不足

`AiEditJob` 只有任务 ID、状态、来源、输入/结果 JSON、错误和时间字段。正式 Worker 至少还需要表达：

- `stage` 和 `progress`。
- `attempt_count`。
- `execution_token_hash` 或等价领取令牌。
- `lease_owner`、`lease_expires_at`、`heartbeat_at`。
- `cancel_requested_at`、`cancelled_at`。
- 输入指纹、引擎版本、Prompt/模型版本。
- 稳定 `failure_code` 和安全 `error_summary`。
- 开始、最近运行和完成时间。

这些是正式迁入专项的数据模型输入，本次不修改表结构。

### 9.4 现有 artifact 壳不足

`AiEditJobArtifact` 缺少：

- SHA-256。
- 产物状态。
- 生成版本。
- 视频时长、分辨率、帧率。
- 与输入 artifact 的来源关系。
- 完整性校验时间。

`AiEditJobArtifactOut` 当前还会返回 `merchant_id` 和内部 `storage_key`。正式前端契约不应暴露这些内部字段。

推荐外部返回：

```json
{
  "artifact_id": "artifact_xxx",
  "artifact_type": "final_video",
  "file_name": "成片.mp4",
  "mime_type": "video/mp4",
  "file_size_bytes": 12345678,
  "sha256": "...",
  "preview_url": "/ai-edit/artifacts/artifact_xxx/preview",
  "download_url": "/ai-edit/artifacts/artifact_xxx/download"
}
```

`storage_key` 只在 9000 和 Worker 内部使用。

## 10. 可复用的 auto_wechat 现有模式

不需要为 AI剪辑重新发明任务安全规则。日报链路已经提供了可参考模式：

### 10.1 原子领取和令牌条件完成

`app/services/daily_report_job_service.py` 已实现：

1. 短事务原子领取并写 `generation_token`。
2. 事务外执行耗时任务。
3. 按任务 ID + token 条件完成，防旧 Worker 覆盖新结果。
4. token 失效时丢弃本次新产物。
5. 失败时保留已有成功产物。

AI剪辑应复用这个并发语义，不直接复制固定日报字段。

### 10.2 storage_key 和完整性校验

`app/services/daily_report_storage.py` 和 `app/routers/daily_reports.py` 已覆盖：

- 受控根目录。
- 路径穿越和符号链接拒绝。
- SHA-256 和文件大小复验。
- 商户过滤下载。
- 不向响应暴露绝对路径和 storage_key。

日报实现固定 `.xlsx`，不能直接用于视频；应提取或实现等价的视频存储规则。

## 11. 推荐任务状态与阶段

### 11.1 任务状态

建议把“任务状态”和“处理阶段”分开：

```text
queued
  -> running
  -> review_required
  -> succeeded

queued/running/review_required
  -> cancel_requested
  -> cancelled

queued/running/review_required
  -> failed
```

不允许：

- `failed -> succeeded` 直接跳转。
- 已完成任务被旧 Worker 再次回写。
- 取消后仍注册新成片。

### 11.2 处理阶段

```text
ingest
probe
asr
visual_analysis
candidate_generation
planning
render
visual_replacement
subtitle
bgm
verify
publish
```

每次阶段变化都需要记录：

- `stage`。
- 输入摘要，不含敏感明文和绝对路径。
- 开始/结束时间。
- 进度。
- `failure_stage` 和稳定错误码。

### 11.3 Worker 领取与取消

1. 9000 创建 `queued` 任务。
2. Worker 通过数据库条件更新原子领取。
3. 数据库只保存领取令牌哈希或不可逆摘要。
4. Worker 定时续租和检查取消标记。
5. 取消 FFmpeg 时终止完整进程树并清理任务临时目录。
6. 租约过期任务可按最大尝试次数重领。
7. 完成和失败都必须带有效令牌条件更新。

## 12. 已批准运行架构

### 12.1 控制面与执行面

```text
9000 控制面
  - NewCar 登录态消费
  - auto_wechat:ai_edit 权限
  - 可信 merchant_id
  - 素材、任务和 artifact metadata
  - 公共素材、缩略图和可选云端产物
  - 取消、重试和审计

19000 小高AI微信助手
  - 本地受管素材和默认单任务队列
  - 启动、监管和取消随包剪辑子进程
  - 与 9000 通信并回写安全进度

ai_edit_worker.exe（Python 3.11）
  - ASR/视觉/规划/渲染/字幕/BGM
  - 自动增稳和媒体强校验
  - 任务目录内产物、进度和诊断
```

### 12.2 独立运行环境

`auto_edit` 要求 Python 3.11；当前 `Dockerfile.backend.dev` 使用 Python 3.10，并且没有安装 FFmpeg 和中文字体。视觉、ASR 和 PyTorch 依赖也不应进入 9000 通用镜像。

随小高AI微信助手安装包提供独立 Python 3.11 `ai_edit_worker.exe`，至少固定：

- Python 3.11 小版本。
- FFmpeg/ffprobe 构建和编码器能力。
- 中文字体及字体探测。
- FunASR、PyTorch、OpenCV、YOLO、open_clip 版本。
- 模型权重缓存目录和只读运行策略。
- CPU、内存、GPU、临时磁盘和单任务并发配置。

### 12.3 临时目录规则

每个任务独立目录：

```text
work/{job_id}/{attempt_token}/
  input/
  stages/
  output/
  diagnostics/
```

目录名只能来自服务端生成的受控标识。任务完成、失败或取消后按保留策略清理，不能长期共享外部 `auto_edit/runs`。

## 13. 推荐迁入顺序

### Phase 12 当前范围：本地 MVP

1. 扩展现有任务和产物壳，增加素材、分析、模板和任务素材关系。
2. 19000 建立本地受管素材、单任务队列、取消和重启恢复。
3. 随包剪辑 Worker 迁入必要内核，运行时不调用外部仓库 CLI。
4. 完成素材库、720P 草稿轻量调整、1080P 成片和下载闭环。

### 正式迁入专项 1：契约和安全任务骨架

1. 冻结任务、阶段、素材候选和 artifact 契约。
2. 建立原子领取、租约、取消和安全下载。
3. 建立随包剪辑 Worker、任务目录和 FFmpeg/字体预检。

退出门槛：并发领取、旧令牌回写、取消、路径穿越、跨商户下载测试全部通过。

### 正式迁入专项 2：纯逻辑内核

迁入模型、边界校验、LLM 输出校验、剪辑语法、质量过滤和字幕规则。

退出门槛：目标仓库离线单元测试通过，不依赖外部仓库路径。

### 正式迁入专项 3：最小可播放成片

先完成：

```text
已提供候选片段
  -> 确定性规划或已校验计划
  -> FFmpeg 裁切拼接
  -> 媒体强校验
  -> artifact 发布
```

退出门槛：真实 MP4 在非关键帧裁切、MOV/MKV 输入、音视频同步和取消场景通过。

### 正式迁入专项 4：原始素材到候选片段

接入 ASR、场景分析、候选生成和 Worker 级模型缓存。

退出门槛：无外部 `candidate_segments` 也能从原始素材生成可审计候选；模型不会按场景重复加载或隐式下载。

### 正式迁入专项 5：字幕、BGM 和 LLM 规划

接入版本化 Prompt、基础/动态字幕、字体检查和 BGM 混音。

退出门槛：解析失败安全降级，原始响应不泄露，横竖屏字幕均可用，声音质量通过人工验收。

### 正式迁入专项 6：BrollStudio 素材区间与增稳

接入已审核增稳素材、可用区间、真实画面替换和时间线校验。

退出门槛：后段替换无冻结、区间外画面不变、时长/分辨率/音频/字幕不漂移，未审核素材不能进入成片。

### 正式迁入专项 7：前端真实闭环

接入上传、任务进度、取消、人工复核、预览和受控下载，不显示假任务、假素材或假统计。

退出门槛：有权限和无权限、跨商户、刷新恢复、失败重试及取消路径通过。

## 14. 正式迁入验收门槛

### 14.1 架构

- 运行时不依赖 `E:\work\project\auto_edit`。
- 9000 不执行重型同步任务。
- 剪辑 Worker 可由 19000 独立启动、取消和健康检查。
- 不共享 SQLite；本地绝对路径只存在于 19000/Worker 受控目录，不能进入 9000 或前端契约。

### 14.2 权限与存储

- 所有 `/ai-edit/*` 后端接口校验 `auto_wechat:ai_edit`。
- `merchant_id` 只来自可信上下文。
- 前端不能提交或获取绝对路径、storage_key、领取令牌或原始 LLM 响应。
- 下载按商户、artifact 状态、哈希和大小复验。
- 路径穿越、符号链接、扩展名伪装和跨商户访问被拒绝。

### 14.3 任务可靠性

- 同一任务只有一个有效 Worker。
- 旧 Worker 不能覆盖重试后的结果。
- 取消能终止 FFmpeg 进程树。
- 崩溃租约可回收，重试次数有上限。
- 已成功 artifact 不因后续失败重试被误删。

### 14.4 视频质量

- 支持契约声明的全部输入格式，或在入口明确收窄格式。
- 输出可被 ffprobe 读取且文件非空。
- 时长、分辨率、帧率、音频和时间戳在允许范围内。
- 非关键帧裁切没有密集 PTS 或帧率异常。
- 后段 B-roll 替换从正确源区间首帧开始，不冻结尾帧。
- 字幕和画面替换后音视频时序不漂移。

### 14.5 模型与 LLM

- 日常测试使用桩，不调用真实付费接口。
- Prompt 和模型版本可追踪。
- 输出结构强校验，失败有稳定错误码和安全降级。
- 模型在 Worker 级缓存，任务中不隐式下载。
- 原始响应不进入普通日志或前端 artifact。

## 15. 测试记录

### 15.1 已执行离线测试

在 `auto_edit` 审计基线上执行离线 pytest，结果：

```text
993 passed, 8 deselected
```

该轮测试覆盖了纯逻辑、脚本适配、输入校验、规划、质量规则、字幕、BGM、画面替换报告和大量异常路径。LLM 相关测试使用桩或本地构造响应，没有调用真实 LLM。

### 15.2 有意排除的 8 项

为避免在本次只读迁入审计中生成真实视频、下载模型或加载重型权重，以下测试未执行：

| # | 测试 | 排除原因 |
|---:|---|---|
| 1 | `test_ffmpeg_adapter.py::test_ffmpeg_runner_trims_real_generated_video` | 真实 FFmpeg 生成和裁切视频 |
| 2 | `test_scene_adapter.py::test_pyscenedetect_runner_detects_real_generated_scene_change` | 真实 FFmpeg + PySceneDetect |
| 3 | `test_vision_adapter.py::test_opencv_frame_reader_reads_real_generated_video` | 真实 FFmpeg + OpenCV 读帧 |
| 4 | `test_renderer.py::test_render_produces_playable_final_video_from_single_asset` | 真实成片和 ffprobe |
| 5 | `test_renderer.py::test_render_produces_clean_timeline_on_sparse_keyframe_source` | 真实稀疏关键帧时间线回归 |
| 6 | `test_cli.py::test_cli_run_with_render_produces_final_video` | CLI 真实生成成片 |
| 7 | `test_visual_semantics.py::test_ultralytics_yolo_detector_runs_real_prediction` | 真实 YOLO 权重和推理 |
| 8 | `test_visual_semantics.py::test_open_clip_text_image_scorer_runs_real_similarity` | 真实 open_clip 权重和推理 |

### 15.3 测试结论边界

`993 passed` 证明现有大量离线规则和适配器在当前基线没有明显回归，但不证明：

- 真实 FunASR 模型可用。
- 真实 YOLO/open_clip 可用或不会下载权重。
- 真实 LLM 稳定。
- 真实 FFmpeg 成片质量合格。
- BrollStudio 区间可真实执行。
- Linux Worker 字体和编码器完整。
- 生产多 Worker、取消、租约和商户隔离安全。

这些必须在正式迁入专项中分阶段补测。

## 16. 风险总表

| 风险 | 等级 | 迁入前要求 |
|---|---|---|
| 正式入口缺少 ASR 到候选片段主链 | HIGH | 先冻结原始素材输入契约和阶段编排 |
| 本地脚本子进程无取消和可靠恢复 | HIGH | 统一可取消执行器 + 持久化阶段机 |
| storage_key、绝对路径和 artifact 边界未完成 | HIGH | 受控存储、完整性、商户下载校验 |
| sidecar 不进入真实执行 | HIGH | 计划、dry-run、执行消费同一候选快照 |
| B-roll 区间和时间线错误 | HIGH | 区间契约 + PTS 偏移 + 真实回归 |
| 计划决策超出执行能力 | HIGH | 收窄契约或补真实执行 |
| 视觉模型按场景重复加载 | HIGH | Worker 级模型缓存和离线权重 |
| LLM 原始响应泄露 | HIGH | 诊断隔离、保留期、禁止前端 artifact |
| 路虎样片规则污染其他商户 | HIGH | 通用规则和版本化模板分离 |
| 独立 Worker 运行环境缺失 | HIGH | Python 3.11 + FFmpeg + 字体 + 模型镜像 |
| 字幕固定 720x1280 和宿主字体 | MEDIUM | 响应式画布和字体预检 |
| 源码部分中文错误信息乱码 | MEDIUM | 稳定错误码和中文文案 |
| 源码与模型许可证未确认 | HIGH | 迁入和对外交付前完成权属审查 |

## 17. 源码证据索引

| 结论 | 文件和位置 |
|---|---|
| 正式入口接受多种视频扩展名 | `scripts/run_client_material_pipeline.py:57-125` |
| 正式入口强制 candidates/reference | `scripts/run_client_material_pipeline.py:186-202` |
| `--skip-asr` 只有参数声明 | `scripts/run_client_material_pipeline.py:313-328` |
| 正式入口三个主步骤 | `scripts/run_client_material_pipeline.py:476-574` |
| `reuse-existing` 只看文件存在 | `scripts/run_client_material_pipeline.py:577-581` |
| 主脚本直接阻塞式 subprocess | `scripts/run_client_material_pipeline.py:1676-1677` |
| 渲染桥只扫描 MP4 | `scripts/render_llm_editing_preview.py:98-99`、`src/auto_edit/llm_render_bridge.py:445-446` |
| FunASR 前半段存在 | `src/auto_edit/transcription.py:28-120` |
| 视觉分析前半段存在 | `src/auto_edit/visual_analysis.py:67-142` |
| 候选片段生成存在 | `src/auto_edit/multi_planner.py:416-497` |
| 临时全链 runner | `scripts/dev/run_fourth_client_001_full_once.py:45-135` |
| 临时 runner 视觉标签读取错误 | `scripts/dev/run_fourth_client_001_full_once.py:503-510`、`src/auto_edit/visual_analysis.py:223-234` |
| sidecar 不包含可用区间 | `src/auto_edit/material_semantic_tag_sidecar.py:68-160` |
| 真实执行不消费 sidecar 候选 | `scripts/run_client_material_pipeline.py:990-1076` |
| 执行器只执行 replace | `src/auto_edit/visual_replacement_execution.py:174-202` |
| 替换时间线滤镜 | `src/auto_edit/visual_replacement_execution.py:213-255` |
| 输出校验仅阻断音频丢失 | `src/auto_edit/visual_replacement_execution.py:257-282` |
| 计划校验允许三种执行决策 | `src/auto_edit/visual_replacement_plan_validator.py:16-28` |
| YOLO/open_clip 重复建模 | `src/auto_edit/visual_analysis.py:349-373`、`src/auto_edit/adapters/vision.py:168-232` |
| 动态字幕固定分辨率和宋体 | `src/auto_edit/subtitle_dynamic_highlight.py:14-16,565-570` |
| 基础字幕固定微软雅黑 | `src/auto_edit/subtitle_render_basic.py:114-120` |
| LLM 解析失败写原始响应 | `src/auto_edit/llm_client.py:495-510` |
| 本地 JSON 任务库 | `src/auto_edit/dealer_task_store.py:37-149,183-185` |
| 路虎样片默认逻辑链 | `src/auto_edit/reference_script.py:1-112` |
| auto_wechat 任务和产物壳 | `app/models.py:1303-1341` |
| 当前 schema 暴露 storage_key | `app/schemas.py:2077-2101` |
| 日报原子 claim 模式 | `app/services/daily_report_job_service.py:1-12,202-282` |
| 日报安全 storage_key 模式 | `app/services/daily_report_storage.py:31-100` |

## 18. 最终决策

### 18.1 可以复用

优先复用 `auto_edit` 的纯逻辑内核、结构化校验、时间边界、剪辑语法、质量规则、字幕规则和测试资产。

### 18.2 不能直接复用

不能直接复用本地 JSON 任务库、外部绝对路径、脚本套脚本总编排、`runs` 目录、开发 runner 和样片专用默认策略。

### 18.3 正式迁入前必须先完成

1. 按已批准设计制定 Phase 12 逐任务执行包。
2. 冻结任务、素材候选和 artifact 契约。
3. 建立 19000 本地队列、随包 Worker、取消和受控存储。
4. 修复格式发现、sidecar 执行、B-roll 区间和时间线问题。
5. 建立真实 FFmpeg、模型、字体和多商户安全验收集。

当前最稳妥的实施原则是：**迁内核，重写边界；先完成可恢复的最小成片，再接 ASR、模型和 BrollStudio。**
