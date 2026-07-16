# AI 剪辑 Worker 第三方许可证清单

> 冻结设计：`docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md` §12.2。
> 执行包：`docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md` Task 8 Step 3。
> Task 11 测试交付执行包：`docs/superpowers/plans/2026-07-16-phase12-task11-single-entry-test-exe-execution-package.md`。

## 分发门禁

**缺少可分发依据时禁止形成客户安装包。** 本清单覆盖随 `ai_edit_worker.exe` 分发的全部第三方二进制与权重。源码级本地测试不阻塞，但对外交付前必须逐项确认下列组件的许可证允许随包分发，并在 `scripts/build_ai_edit_worker_exe.ps1` 构建时校验许可证文件存在。

未完成权属审查或许可证缺失的组件，不得打包进客户安装目录 `dist/local-agent`。

## Task 11 甲方测试包分发线

“测试版”不是许可证豁免。Task 11 只允许构建最小许可安全载荷，并在检查点 D2 前保持 `BUILT_PENDING_APPROVAL`、`BLOCKED_BY_DISTRIBUTION_EVIDENCE` 或 `BLOCKED_BY_BUILD_OR_SMOKE`：

1. 测试包不得调用正式 `DistributionMode=Customer`，不得创建或读取 `LICENSE_CONFIRMED.txt`。
2. 测试包显式排除 EasyOCR、PyTorch、torchvision、OpenCV、Pillow、FunASR、Ultralytics/YOLO、open_clip、模型权重和未确认字体；微信 OCR、真实 ASR、视觉标签与智能空镜匹配不属于该测试件能力。
3. 测试包仅可包含实际运行需要且已附可分发依据的 Python 运行时、Tcl/Tk、PyInstaller bootloader、Local Agent 控制面、AI 剪辑 Worker、FFmpeg/ffprobe 和对应许可证文本；必须按实际 PyInstaller archive 清单核对，不能只审 requirements 文件。
4. FFmpeg 构建参数含 `--enable-nonfree` 时禁止分发；允许构建也必须按实际组件采用的许可证口径内嵌文本、完整构建信息和源码获取说明。Task 11 当前要求 Vid.Stab，因此按 GPL 口径审查。
5. 构建后必须扫描 payload 与 PyInstaller archive；禁入组件、权重、`.env`、token 和正式许可证确认标记任一命中即阻断。
6. 四方检查点 D2 PASS 且当前窗口明确批准前，不得把测试 EXE 发送甲方。

## 组件清单

### FFmpeg（含 ffprobe）
- 来源：`https://ffmpeg.org/`
- 构建：Task 11 优先使用可枚举的最小 Windows GPL 构建；如使用 Gyan full build，必须按 `-buildconf` 覆盖全部 `--enable-lib*` 外部组件的独立许可证映射，未知项即阻断
- 许可证：LGPL 2.1+（默认）或 GPL 2+（启用 --enable-gpl，含 libvidstab 时通常为 GPL）
- 分发依据：LGPL/GPL 允许随包分发二进制，但需附许可证文本与源码获取说明
- 注意：`libx264` 为 GPL 组件，启用后整体 FFmpeg 二进制按 GPL 分发

### libvidstab（Vid.Stab 视频增稳）
- 来源：`https://github.com/georgmartius/vid.stab`
- 许可证：GPL 2.0 或更高版本
- 用途：Worker `stabilizer.py` 两遍 Vid.Stab 增稳（保留音频，禁 `-an`）
- 分发依据：随 FFmpeg 二进制分发时整体按实际构建采用的 GPL 口径履行义务，附 GPL 文本、完整 `ffmpeg -L/-version/-buildconf`、构建来源和对应源码获取说明

### libx264（H.264 编码）
- 来源：`https://www.videolan.org/developers/x264.html`
- 许可证：GPL 2+
- 用途：Worker 渲染 `libx264` 编码器
- 注意：GPL 组件，启用后 FFmpeg 二进制与下游分发须遵守 GPL 条款

### FunASR（语音识别）
- 来源：`https://github.com/modelscope/FunASR`
- 许可证：MIT（代码）/ 模型权重按各自协议（paraformer 等多为 CC-BY-NC 或 Apache 2.0，需逐模型确认）
- 用途：Worker ASR 转写主口播
- 分发依据：MIT 代码可分发；模型权重须确认商用许可，否则不可随包分发

### PyTorch
- 来源：`https://pytorch.org/`
- 许可证：BSD 3-Clause（含 PyTorch 与 libtorch 二进制）
- 用途：Worker 视觉模型（YOLO/open_clip）与张量计算运行时
- 分发依据：BSD 3-Clause 允许分发，附许可证文本

### YOLO（Ultralytics）
- 来源：`https://github.com/ultralytics/ultralytics`
- 许可证：AGPL-3.0（代码）/ 模型权重按各自协议
- 用途：Worker 视觉标签检测
- 注意：AGPL-3.0 对分发与网络服务有 copyleft 要求，商用分发前必须法务确认；不可在未确认前随客户安装包分发

### open_clip（图文匹配）
- 来源：`https://github.com/mlfoundations/open_clip`
- 许可证：MIT（代码）/ 模型权重按各自协议
- 用途：Worker 图文匹配评分
- 分发依据：MIT 代码可分发；权重须确认协议

### 字体（中文字幕烧录）
- 来源：随包分发的确定中文字体（构建脚本 `FontDir` 参数指定）
- 许可证：按字体各自协议（如思源黑体 SIL OFL 1.1、阿里巴巴普惠字体免费授权等）
- 用途：Worker 字幕烧录，依赖预检确定字体，不依赖宿主机字体
- 分发依据：OFL/免费授权字体可分发，附字体许可证文本；商用收费字体不可随包分发

## 校验要求

正式脚本 `scripts/build_ai_edit_worker_exe.ps1` 当前只强制校验：

1. FFmpeg/ffprobe 存在且含 `vidstab` 滤镜（libvidstab 可用）。该正式脚本尚未保存 `-L/-version/-buildconf` 或拒绝 `--enable-nonfree`，因此不能作为 Task 11 分发证据。
2. 模型目录存在（FunASR/YOLO/open_clip 权重）。
3. 字体目录存在（中文字体预检）。
4. 本许可证文件存在（`THIRD_PARTY_NOTICES.md`）。

Task 11 独立脚本 `scripts/build_phase12_test_payload.ps1` 另行强制保存 `ffmpeg -L/-version/-buildconf`、拒绝 `--enable-nonfree`，并要求全部 `--enable-lib*` 外部组件与许可证映射精确一致；不得把该计划能力误记为正式脚本已具备。

缺任一项 → `throw` 明确失败，禁止形成客户安装包。

## 权属审查状态（2026-07-15）

- FFmpeg/libvidstab/libx264：所选构建包含 GPL 组件时整体按 GPL 分发；须附 GPL 文本、构建信息和源码获取说明（待 Task 11 实际构建证据确认）。
- PyTorch：BSD 3-Clause 可分发。
- FunASR 代码：MIT 可分发；**模型权重商用许可待确认**。
- YOLO（Ultralytics）：**AGPL-3.0，商用分发待法务确认**，未确认前不随客户安装包分发。
- open_clip 代码：MIT 可分发；权重协议待确认。
- 字体：待选定具体字体并确认协议。

**结论：截至 2026-07-16，正式客户安装包仍因 YOLO AGPL、FunASR/open_clip 模型权重和字体分发依据未完成而保持 `NOT_BUILT`。Task 11 测试 EXE 只允许走独立最小载荷与独立四方分发审查；当前状态为预检/合同冻结，尚未构建、尚未批准对外交付。**
