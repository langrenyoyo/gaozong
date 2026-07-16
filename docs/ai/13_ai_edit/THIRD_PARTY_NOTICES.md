# AI 剪辑 Worker 第三方许可证清单

> 冻结设计：`docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md` §12.2。
> 执行包：`docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md` Task 8 Step 3。
> Task 11 测试交付执行包：`docs/superpowers/plans/2026-07-16-phase12-task11-single-entry-test-exe-execution-package.md`。

## 分发门禁

**缺少可分发依据时禁止形成客户安装包。** 本清单覆盖随 `ai_edit_worker.exe` 分发的全部第三方二进制与权重。源码级本地测试不阻塞，但对外交付前必须逐项确认下列组件的许可证允许随包分发，并在 `scripts/build_ai_edit_worker_exe.ps1` 构建时校验许可证文件存在。

未完成权属审查或许可证缺失的组件，不得打包进客户安装目录 `dist/local-agent`。

## Task 11 甲方测试包口径

按用户决定，本清单仅保留为参考，不作为 Task 11 开发、构建或测试交付门禁。Task 11 构建脚本不得读取 `LICENSE_CONFIRMED.txt`，也不要求许可证文件、组件映射、FFmpeg 构建信息、archive 扫描或安全软件扫描；最终只交付 `小高AI系统测试版.exe`。

## 组件清单

### FFmpeg（含 ffprobe）
- 来源：`https://ffmpeg.org/`
- 构建：Task 11 保存实际 `-L/-version/-buildconf`、拒绝 `--enable-nonfree`，并附 GPL 文本与源码获取说明；正式安装包再完成外部组件逐项映射
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

Task 11 使用独立单入口构建脚本，不调用本节正式安装包校验，也不读取本许可证文件。

缺任一项 → `throw` 明确失败，禁止形成客户安装包。

## 权属审查状态（2026-07-15）

- FFmpeg/libvidstab/libx264：所选构建包含 GPL 组件时整体按 GPL 分发；须附 GPL 文本、构建信息和源码获取说明（待 Task 11 实际构建证据确认）。
- PyTorch：BSD 3-Clause 可分发。
- FunASR 代码：MIT 可分发；**模型权重商用许可待确认**。
- YOLO（Ultralytics）：**AGPL-3.0，商用分发待法务确认**，未确认前不随客户安装包分发。
- open_clip 代码：MIT 可分发；权重协议待确认。
- 字体：待选定具体字体并确认协议。

**结论：截至 2026-07-16，正式客户安装包仍为 `NOT_BUILT`，原因是尚未启动正式安装包任务，不再以本清单作为 Task 11 构建阻断。Task 11 状态为 `APPROVED_FOR_DIRECT_BUILD`。**
