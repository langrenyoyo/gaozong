# BrollStudio 空镜素材复用与视频增稳评估报告

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 评估日期 | 2026-07-14 |
| 被评估项目 | `E:\work\project\BrollStudio_空镜素材增稳分析入库工具_交付包_20260714_114227` |
| 目标项目 | `E:\work\project\auto_wechat` |
| 目标业务域 | AI剪辑、小高素材库 |
| 评估方式 | 只读源码审计、离线单元测试、随包 FFmpeg 能力检查、合成视频运行验证 |
| 文档状态 | 迁入能力证据基线；当前产品和架构边界见 `2026-07-15_Phase12_AI剪辑本地MVP设计.md` |

## 2. 结论摘要

BrollStudio 对 `auto_wechat` 有明确复用价值，视频增稳代码也真实存在并能够运行。

最准确的产品定位是：

```text
BrollStudio = 空镜素材预处理 + 增稳 + 多模态标注 + 可用区间管理
```

它适合成为 AI剪辑链路上游的“空镜素材加工与素材库”子模块，但不能直接充当完整的一键成片引擎。

交付文档明确排除了以下能力：

1. 口播 ASR。
2. 口播剪辑。
3. 字幕生成与排版。
4. BGM 编排。
5. 时间线合成。
6. 最终成片导出。

因此，BrollStudio 可以补齐 `auto_wechat` 的素材入库和增稳能力，但一键剪辑主流程仍需由 `auto_edit` 或后续迁入的正式剪辑内核提供。

## 3. 已确认的完整能力链路

交付包当前实现的处理链路为：

```text
导入原始空镜
  -> SHA-256 内容去重
  -> 自动 / 单点 / 框选 / 涂抹选择增稳参考区域
  -> 视频增稳
  -> 原片与增稳片对比确认
  -> 火山方舟多模态分析
  -> 人工复核摘要、标签、可用区间
  -> SQLite 素材库入库
  -> 按标签和可用时长检索素材
```

证据：

- `空镜素材增稳分析入库功能交接文档.md:14-28`
- `source/README.md`
- `source/broll_asset_analyzer/analyzer.py`
- `source/broll_asset_analyzer/db.py`

## 4. auto_wechat 当前承接条件

`auto_wechat` 已有 AI剪辑任务和产物的结构预留：

- `app/models.py:1303`：`AiEditJob`。
- `app/models.py:1324`：`AiEditJobArtifact`。
- `migrations/versions/0027_xiaogao_phase1_core.sql:324`：SQLite 迁移任务壳。
- `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py`：PostgreSQL 对应迁移。
- `app/schemas.py`：AI剪辑任务与产物输出结构。

当前尚未发现以下正式实现：

- `app/routers/ai_edit.py`。
- 19000 AI剪辑协调层和随包 `ai_edit_worker.exe`。
- AI剪辑素材资产、标签、可用区间的正式数据模型。
- AI剪辑任务领取、运行、取消和失败回写服务。
- AI剪辑真实前端接口。

前端页面也明确标记真实接口尚未接入：

- `frontend/src/pages/AiVideoEditor.tsx:23-25`。
- `frontend/src/pages/MaterialLibrary.tsx:23-25`。

已批准边界要求 AI剪辑由小高AI微信助手监管随包 Python 3.11 子进程，具备独立启动、配置、健康检查、日志、取消和异常处理能力。入口权限继续使用 `auto_wechat:ai_edit`。

## 5. 复用矩阵

| 能力 | 来源 | 复用价值 | 建议 |
|---|---|---:|---|
| FFmpeg 自动全画面增稳 | `stabilizer.py` | 高 | 第一阶段优先迁移 |
| 点选/框选/蒙版跟踪增稳 | `tracking_stabilizer.py`、`selection.py` | 中 | 完成真实素材质量验证后迁移 |
| SHA-256、ffprobe、抽帧、代理视频 | `video.py` | 高 | 迁入 Worker 并统一子进程封装 |
| 增稳失败阻断模型和入库 | `analyzer.py` | 高 | 保留业务门禁语义 |
| 素材标签和可用/无效区间契约 | `prompts.py` | 高 | 作为正式结构化分析契约的输入 |
| 原片/增稳片对比视频 | `desktop_jobs.py` | 中 | 复用 FFmpeg 处理思路 |
| 桌面文件任务状态 | `desktop_jobs.py` | 中低 | 只复用状态设计，不迁文件任务实现 |
| SQLite 素材库 | `db.py` | 低 | 不迁入，按 PostgreSQL 路线重建 |
| 当前素材检索 | `db.py:225-265` | 低 | 不是语义检索，不作为正式搜索引擎 |
| PySide6 桌面界面 | `desktop.py` | 低 | 不迁入，继续使用 React 前端 |
| 固定豆包客户端 | `doubao_client.py`、`ark_files.py` | 中低 | 只复用接口思路，重新适配项目基础设施 |
| Windows 桌面打包脚本 | `build_desktop.ps1` | 低 | 不作为服务端交付方式 |

## 6. 视频增稳代码评估

### 6.1 自动全画面增稳

核心实现：

```text
source/broll_asset_analyzer/stabilizer.py
VidStabPreprocessor.process()
```

处理方式为标准两遍 FFmpeg Vid.Stab：

1. 使用 `vidstabdetect` 提取相对运动轨迹。
2. 使用 `vidstabtransform` 平滑轨迹并重新编码视频。
3. 提供 `light`、`medium`、`strong` 三档参数。
4. 使用源文件 SHA-256 建立缓存目录。
5. 缓存复用时校验源哈希、预设和编码参数。
6. 执行前检查 `ffmpeg`、`ffprobe` 和两个 Vid.Stab 滤镜。
7. 支持超时、错误日志、临时文件和原子替换最终输出。
8. Windows 下通过 `CREATE_NO_WINDOW` 避免弹出命令行窗口。

这部分是最接近生产候选的代码，建议作为首批迁入范围。

### 6.2 自动增稳迁入前必须修正

1. **音频行为不一致**

   自动模式在两遍命令中使用 `-an`，最终视频不保留音频。空镜素材通常可以接受，但正式接口必须明确这是产品行为还是缺陷，不能隐式丢失音轨。

2. **并发处理存在文件竞争**

   相同源哈希会共享哈希目录、`motion.trf`、临时输出和报告文件。两个 Worker 并发处理同一素材时可能互相删除或覆盖文件，需要增加数据库任务领取、运行锁或任务级临时目录。

3. **自动模式不能及时取消**

   当前使用阻塞式 `subprocess.run()`。长视频进入 FFmpeg 后只能等待完成或超时，正式 Worker 应支持终止子进程及清理临时产物。

4. **缓存版本信息不足**

   当前缓存校验未纳入 FFmpeg 构建版本和算法版本。部署升级后可能继续复用旧结果，应将处理器版本、FFmpeg 版本和参数摘要纳入缓存身份。

5. **本地绝对路径不符合项目存储约束**

   输入、输出和报告均使用绝对路径。迁入后应采用：

   ```text
   storage_key -> Worker 受控临时目录 -> 输出上传 -> artifact storage_key
   ```

6. **哈希信任边界需要收紧**

   `VidStabPreprocessor.process()` 接收外部传入的 `source_hash`，自身不重新确认哈希与文件内容一致。正式 Worker 应自行计算或验证内容哈希。

### 6.3 人工目标跟踪增稳

核心实现：

```text
source/broll_asset_analyzer/tracking_stabilizer.py
source/broll_asset_analyzer/selection.py
```

它支持：

- 单点选择。
- 矩形框选。
- 涂抹蒙版。
- 平滑跟随和目标锁定。
- 进度回调和取消检查。
- 可选音频重新混流。

算法使用 OpenCV：

```text
goodFeaturesToTrack
  -> calcOpticalFlowPyrLK
  -> 特征点位移中值和异常值剔除
  -> 中心轨迹移动平均
  -> warpAffine 平移画面
```

当前实现没有完整估计旋转、缩放、仿射或透视矩阵，本质上是基于目标中心的二维平移增稳。因此不能直接视为通用生产增稳算法。

已确认的限制：

1. 桌面版只支持在第一帧选择目标。
2. 跟踪失败时继续沿用上一帧位移，连续失败可能产生漂移。
3. 跟踪成功率门槛为 35%，真实业务需要更严格质量判定和人工复核。
4. 中间产物是全分辨率 MJPG AVI，长视频和 4K 素材可能产生明显磁盘放大。
5. Python/OpenCV 逐帧处理会占用较多 CPU，不宜运行在 9000 API 请求进程中。

建议将该模式放到自动增稳稳定后再评估，并使用真实手持、低纹理、快速移动、旋转、缩放和滚动快门素材建立验收集。

## 7. 其他可复用模块

### 7.1 视频基础工具

`video.py` 中可复用：

- `file_sha256()`：4 MiB 分块计算，支持进度与取消。
- `probe_video()`：读取时长、分辨率、帧率和文件大小。
- `extract_sample_frames()`：按时间均匀抽取分析帧。
- `make_analysis_proxy()`：生成低分辨率分析代理视频。

迁入时需要统一到 AI剪辑 Worker 的子进程执行器，补齐无窗口运行、超时、日志脱敏和取消能力。

### 7.2 增稳与入库门禁

`analyzer.py` 的业务顺序值得保留：

```text
增稳成功
  -> 校验增稳结果属于当前源文件
  -> 确认输出文件存在且可探测
  -> 调用模型分析
  -> stabilization_status=completed
  -> 允许入库
```

其中两项门禁尤其重要：

- 增稳结果的 `source_hash` 必须与当前源文件一致。
- 只有完成增稳且产物真实存在的分析结果才允许入库。

### 7.3 标签与可用时间区间

`prompts.py` 已覆盖：

- 主体。
- 场景。
- 镜头运动。
- 景别。
- 光线和颜色。
- 情绪。
- 适用口播内容。
- 使用限制。
- 可用区间和无效区间。
- 区间稳定性评分和运动类型。

这套字段能够支撑后续“口播片段 -> 空镜素材区间”的匹配。但正式迁入还需使用 Pydantic 或等效结构校验模型输出，检查分值范围、重叠区间、区间覆盖和异常输出，不能只依赖提示词。

### 7.4 人工复核状态

`desktop_jobs.py` 中的状态可作为正式任务状态设计的参考：

```text
imported
stabilizing
waiting_stabilization_review
analyzing
waiting_analysis_review
committing
completed / failed / cancelled
```

文件系统 `job.json` 不是正式多 Worker 状态存储，迁入后应由 PostgreSQL metadata 维护状态、领取令牌和版本条件更新。

## 8. 不应直接迁入的实现

### 8.1 SQLite 数据库

`db.py` 使用：

- `sqlite3.connect()`。
- `PRAGMA`。
- SQLite `ON CONFLICT` 和 `INSERT OR IGNORE`。
- 本地绝对文件路径。
- 进程共享 SQLite 文件。

这些实现与项目 PostgreSQL 目标路线、商户隔离、`storage_key` 和独立服务边界冲突。可以参考资产、标签和区间的数据语义，但不能复制数据库实现。

### 8.2 PySide6 桌面界面

`desktop.py` 与现有 React 页面重复，且依赖本机桌面状态和共享数据目录。正式产品继续使用：

- `frontend/src/pages/AiVideoEditor.tsx`。
- `frontend/src/pages/MaterialLibrary.tsx`。

桌面的五步工作流和交互状态可以作为 React 产品设计参考，界面代码本身不迁入。

### 8.3 固定豆包客户端

当前客户端存在以下产品化缺口：

- 模型默认值固定。
- 缺少统一重试和退避。
- 缺少商户上下文。
- 缺少算力消耗上报。
- 缺少项目统一审计日志。
- 缺少调用幂等和任务恢复。
- 错误正文需要进一步脱敏。

建议保留提示词和请求/响应契约，使用项目统一配置和模型调用适配器重新实现。

## 9. 检索能力的真实边界

交接文档描述 FunClip 会“按语义和可用时长检索”，但本交付包自身没有向量或 embedding 检索实现。

`BrollAssetLibrary.search()` 的实际逻辑是：

1. 按空格和逗号拆分查询词。
2. 拼接素材标签、摘要和区间描述。
3. 对每个查询词做小写子串包含判断。
4. 按命中词数量和质量分排序。

因此它是关键词包含匹配，不是真正语义检索。交付包中也没有 FunClip 的实际时间线或画面替换实现，只有 SQLite 调用示例。

一期可以先使用结构化标签和明确关键词完成素材筛选。确需语义匹配时，可参考 `apps/xg_douyin_ai_cs/llm/ark_embedding_client.py` 的文本 embedding 调用模式，将素材摘要/标签和口播片段映射到向量，但必须遵守：

1. AI剪辑 metadata 真源仍为 PostgreSQL。
2. 向量库只保存 embedding 和检索副本。
3. AI剪辑使用独立集合和业务作用域，不与 RAG 文档集合混用。
4. 前端不直连 9100 或 Milvus。
5. 现有 Ark embedding 客户端当前只支持文本，不支持直接输入图片或视频。

## 10. 推荐迁入架构

### 10.1 最小一期

第一阶段只迁移：

```text
内容哈希
  + ffprobe
  + FFmpeg Vid.Stab 自动增稳
  + 任务状态门禁
  + storage_key 产物落库
```

不同时迁移 ROI 跟踪、PySide6、SQLite、模型分析和语义检索，先形成最小可验证闭环。

### 10.2 推荐调用链

```text
React（与小高AI微信助手同机）导入素材
  -> 9000 鉴权并创建可信素材 ID
  -> 19000 复制到本地受管目录
  -> 随包 ai_edit_worker.exe 计算 SHA-256、ffprobe、执行自动增稳
  -> 19000 回写素材 metadata、缩略图、状态和安全错误摘要
  -> React 查询状态并预览对比
  -> 用户主动选择后才上传云端产物
```

9000 和 19000 主进程都不应在同步 HTTP 请求内执行长时间视频转码。

### 10.3 素材库 metadata

当前 `AiEditJobArtifact` 只能表达任务产物，不能完整替代长期素材库。正式数据模型至少需要表达：

- 可信 `merchant_id`。
- 原始素材本地设备 ID/受管引用，或用户主动上传后的 `storage_key`。
- 增稳素材本地设备 ID/受管引用，或用户主动上传后的 `storage_key`。
- 源内容 SHA-256。
- 素材处理状态。
- 增稳模式、参数和算法版本。
- 时长、分辨率、帧率和文件大小。
- 标签与质量分。
- 可用和无效时间区间。
- 创建、更新、审核和失败信息。

业务资产必须按商户隔离。底层文件可以评估内容去重，但不能因为两个商户上传相同内容而互相看到资产、标签或任务。

文件存储可以参考 `app/services/daily_report_storage.py` 的受控根目录、路径穿越校验和 `storage_key` 设计，但该模块固定 `.xlsx`，不能直接用于视频。

### 10.4 第二阶段及以后

建议按以下顺序扩展：

1. 自动增稳后的原片/成片对比与人工确认。
2. 多模态标签分析和区间复核。
3. 口播片段与空镜区间匹配。
4. ROI 跟踪增稳。
5. 完整时间线、字幕、BGM 和最终成片导出。

## 11. 运行环境与依赖

交付包随附：

```text
BrollStudio/_internal/ffmpeg/ffmpeg.exe
BrollStudio/_internal/ffmpeg/ffprobe.exe
```

已确认随包 FFmpeg：

- 版本：`8.1.1-full_build-www.gyan.dev`。
- 包含 `vidstabdetect`。
- 包含 `vidstabtransform`。
- 包含 `libx264`。

当前小高AI微信助手构建环境是 Python 3.10.20，而 `auto_edit` 要求 Python 3.11；9000/9100 容器也不具备完整媒体依赖。因此正式迁入使用随安装包交付的 Python 3.11 `ai_edit_worker.exe`、固定 FFmpeg/ffprobe 和字体，不把重依赖塞进 9000、9100 或 19000 主进程。

## 12. 风险清单

| 风险 | 等级 | 处理建议 |
|---|---|---|
| 相同素材并发处理互相覆盖临时文件 | HIGH | 数据库原子领取、运行锁、任务级临时目录 |
| 绝对路径和共享 SQLite 与多商户冲突 | HIGH | PostgreSQL metadata + storage_key |
| 随包 FFmpeg 再分发许可证要求 | HIGH | 发布前完成许可证和源码提供义务评估 |
| 交付源码缺少项目级许可证 | HIGH | 迁入前确认代码权属和内部授权 |
| 自动模式静默丢弃音频 | MEDIUM | 明确产品契约或保留可选音频 |
| ROI 模式只处理平移 | MEDIUM | 真实素材验收，不标称通用增稳 |
| ROI 临时 MJPG 文件磁盘放大 | MEDIUM | 限制素材、改流式/低损耗中间方案 |
| FFmpeg 长任务无法及时取消 | MEDIUM | 子进程生命周期管理和清理 |
| 当前搜索不是语义检索 | MEDIUM | 修正文档口径，后续独立建设向量检索 |
| 模型输出校验不足 | MEDIUM | 结构化 schema、区间和分值验证 |
| 缺少真实视频质量基准 | MEDIUM | 建立代表性素材集和人工评分基线 |

## 13. 许可证与代码权属

交付包中未发现项目级 `LICENSE`、`LICENCE`、`COPYING` 或 `NOTICE` 文件；仅部分第三方依赖目录带有各自许可证。

随包 FFmpeg 显示：

```text
--enable-gpl
--enable-version3
--enable-static
--enable-libvidstab
--enable-libx264
```

这不阻止内部技术评估，但在复制源码、将 FFmpeg 放入新镜像或对外交付安装包前，必须确认：

1. BrollStudio 业务源码的所有权和迁入授权。
2. FFmpeg 及其静态链接组件的许可证履行方式。
3. 是否需要附带许可证文本、构建信息或对应源码获取方式。

本文只记录工程风险，不构成法律意见。

## 14. 验证记录

### 14.1 离线单元测试

执行：

```powershell
python -m unittest discover -s tests -p "test_s*.py" -v
```

结果：

```text
11 tests passed
```

覆盖：

- 选区蒙版和指纹。
- 移动平均帧数保持。
- 增稳缓存复用。
- SHA-256 内容去重。
- 旧素材不参与检索。
- 检索返回增稳产物路径。
- 增稳失败阻断模型调用和数据库写入。
- 模型上传和数据库均使用增稳视频。

完整 `unittest discover` 未通过，原因是当前 Python 环境缺少 `PySide6`，导致 `test_desktop_smoke.py` 导入失败。该文件包含的 3 个桌面测试未在本环境独立执行。交付包 `VERSION.json` 声明构建环境曾有 `14 passed`，本次未独立验证其中 3 个桌面测试。

### 14.2 FFmpeg 能力检查

使用随包 `ffmpeg.exe -hide_banner -filters` 检查，确认存在：

```text
vidstabdetect
vidstabtransform
```

### 14.3 自动增稳运行验证

使用随包 FFmpeg 生成一段 2 秒、480x360 的合成抖动视频，再调用 `VidStabPreprocessor`：

- 两遍 Vid.Stab 执行成功。
- 输出 MP4 存在。
- 输出时长为 2.0 秒。
- 输出分辨率为 480x360。
- 第二次处理命中缓存，`reused=True`。

### 14.4 ROI 跟踪运行验证

对同一合成视频执行矩形 ROI 跟踪增稳：

- 输出 MP4 存在。
- 输出时长为 2.0 秒。
- 输出分辨率为 480x360。
- 该合成样本跟踪成功率为 100%。

合成视频验证只能证明执行链和产物有效，不能证明真实手持、低纹理、快速移动、旋转、缩放、滚动快门或 4K 素材的最终画质。

## 15. 源码证据索引

| 结论 | 文件和位置 |
|---|---|
| 自动两遍 Vid.Stab | `source/broll_asset_analyzer/stabilizer.py:76-187` |
| 缓存和 FFmpeg 能力检查 | `source/broll_asset_analyzer/stabilizer.py:196-287` |
| 跟踪增稳主流程 | `source/broll_asset_analyzer/tracking_stabilizer.py:65-219` |
| 光流跟踪和二维平移 | `source/broll_asset_analyzer/tracking_stabilizer.py:272-437` |
| ROI 音频混流 | `source/broll_asset_analyzer/tracking_stabilizer.py:439-460` |
| 第一帧选区限制 | `source/broll_asset_analyzer/selection.py:27-42` |
| SHA-256 和视频探测 | `source/broll_asset_analyzer/video.py:24-83` |
| 增稳归属与入库门禁 | `source/broll_asset_analyzer/analyzer.py:93-158` |
| 标签和区间提示词 | `source/broll_asset_analyzer/prompts.py:1-90` |
| SQLite 表和绝对路径 | `source/broll_asset_analyzer/db.py:10-68,85-191` |
| 关键词包含检索 | `source/broll_asset_analyzer/db.py:225-265` |
| 桌面任务状态和对比视频 | `source/broll_asset_analyzer/desktop_jobs.py:12-168` |
| 随包 FFmpeg 路径注入 | `source/broll_asset_analyzer/desktop.py:1221-1231` |

## 16. 最终决策建议

推荐复用，但必须拆分迁入：

```text
第一优先级：Vid.Stab 自动增稳 + SHA-256 + ffprobe + 增稳门禁
第二优先级：标签、可用区间、对比复核
第三优先级：真实语义检索和 ROI 跟踪增稳
不迁入：SQLite 共享库、PySide6 桌面端、绝对路径协议、固定豆包客户端
```

第一阶段的目标应是形成由 19000 监管、可取消、幂等、商户隔离、本地文件默认真源且支持主动云端上传的随包增稳 Worker，而不是一次性搬入整个 BrollStudio。
