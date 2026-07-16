# Phase 12 Task 11 单入口测试 EXE 轻量执行包

> **执行方式：** 执行窗口使用 `executing-plans` 连续完成 Task 11-1~11-3；只在最终发送甲方前硬暂停一次。

**目标：** 生成甲方测试专用 `小高AI系统测试版.exe`，用户只启动这一个 EXE；内部继续使用 Python 3.10 Local Agent 与 Python 3.11 AI 剪辑 Worker 两套隔离运行时。

**状态：** `APPROVED_FOR_IMPLEMENTATION`

## 1. 冻结口径

最终交付目录只有：

```text
小高AI系统测试版.exe
小高AI系统测试版.exe.sha256.txt
```

测试包不是正式安装包，不代表生产验证完成。以下状态不变：

```text
Phase 12：DONE_WITH_CONCERNS
唯一 concern：baota_ai_edit_production_not_verified
正式客户安装包：NOT_BUILT
Phase 13：NOT_STARTED
宝塔生产验证：NOT_STARTED，Phase 13 完成后统一执行
```

## 2. 只保留的硬约束

1. 甲方只启动一个外层 EXE，不手工启动内部 Worker。
2. Local Agent 与 Worker 保持双运行时、双业务进程，不合并 Python 3.10/3.11。
3. Local Agent token 不写入源码、Git、构建日志或最终 EXE；启动时由用户在掩码框输入。
4. 19000 保持 `127.0.0.1:19000` 且鉴权开启。
5. 测试包不包含 EasyOCR/PyTorch/torchvision/OpenCV/Pillow/FunASR/YOLO/open_clip、模型权重和字体。
6. 不调用 `DistributionMode=Customer`，不创建 `LICENSE_CONFIRMED.txt`，不连接宝塔、生产数据库、真实付费模型或抖音发布接口。
7. 真实 FFmpeg、Worker、PyInstaller 只在本机使用合成媒体验证；甲方发送前必须回传 EXE SHA-256 和测试限制。

## 3. 本轮明确不做

以下控制推迟到正式客户安装包，不阻塞测试 EXE：

- WFP/ETW 网络审计。
- Windows Defender 强制门禁。
- PyInstaller 三份 archive 的逐组件许可证映射。
- FFmpeg full build 全部 `--enable-lib*` 的逐项法务清单。
- 双遍 PyInstaller 构建和 golden vector 指纹。
- Windows Job Object、Known Folder API、junction 闭集扫描。
- 自动更新、安装器、卸载器、系统服务和旧版本自动清理。
- D0/D1 中间检查点和专用 Git worktree。

测试包仍需内嵌 `THIRD_PARTY_NOTICES.md`、FFmpeg `-L/-version/-buildconf`、GPL 文本和源码获取说明；正式安装包再做完整分发审计。

## 4. 文件范围

允许新增或修改：

```text
app/phase12_test_launcher.py
app/local_agent_main.py
local_agent_phase12_test.spec
ai_edit_worker_phase12_test.spec
phase12_test_launcher.spec
requirements-phase12-test-worker.txt
scripts/build_phase12_test_payload.ps1
scripts/build_phase12_single_test_exe.ps1
scripts/generate_phase12_test_payload.py
tests/test_phase12_task11_launcher.py
tests/test_phase12_task11_packaging_contract.py
tests/test_phase12_local_ai_edit_supervisor.py
docs/ai/13_ai_edit/TEST_BUILD_NOTICE_TEMPLATE.md
docs/ai/13_ai_edit/THIRD_PARTY_NOTICES.md
docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md
docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md
docs/ai/05_PROJECT_CONTEXT.md
docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md
docs/superpowers/plans/2026-07-16-phase12-task11-single-entry-test-exe-execution-package.md
```

既有 `local_agent.spec`、`ai_edit_worker.spec` 和正式构建脚本不修改。每次提交只显式暂存本任务文件，不纳入其它脏工作区内容。

## 5. Task 11-1：最小启动器与合同

**Files:**

- Create: `app/phase12_test_launcher.py`
- Create: `tests/test_phase12_task11_launcher.py`
- Modify: `app/local_agent_main.py`
- Modify: `tests/test_phase12_local_ai_edit_supervisor.py`

- [ ] **Step 1：先写红灯测试**

覆盖以下最小合同：

```text
payload 任一文件 SHA-256 不符时拒绝启动
释放目录固定在 %LOCALAPPDATA%\XiaogaoAI\Test\<version>
相对路径含绝对路径、盘符或 .. 时拒绝
19000 端口被占用时不启动、不杀未知进程
token 输入框掩码，token 不落盘、不进日志
Local Agent 只监听 127.0.0.1 且 LOCAL_AGENT_AUTH_REQUIRED=true
Worker 子进程不继承 LOCAL_AGENT_TOKEN(S)、9000 URL 或数据库/internal token
退出时只清理本次持有的 Local Agent 进程树
```

运行：

```powershell
$Python310Exe = 'C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe'
& $Python310Exe -m pytest -q tests/test_phase12_task11_launcher.py tests/test_phase12_local_ai_edit_supervisor.py
```

- [ ] **Step 2：实现最小启动器**

只用 Python 标准库：

1. 从内嵌 `payload_manifest.json` 读取相对路径、文件大小和 SHA-256。
2. 校验后复制到 `%LOCALAPPDATA%\XiaogaoAI\Test\<version>`；同版本已完整则复用，损坏则明确失败，不自动删除。
3. 构建参数写入非秘密配置：测试 API URL、测试前端 URL、merchant_id；token 不进入构建。
4. 启动时用 `tkinter` 掩码输入 token。
5. 子进程环境设置：

   ```text
   LOCAL_AGENT_HOST=127.0.0.1
   LOCAL_AGENT_PORT=19000
   LOCAL_AGENT_AUTH_REQUIRED=true
   AUTO_WECHAT_SERVER_URL=<测试API>
   LOCAL_AGENT_TOKEN=<运行时输入>
   LOCAL_AGENT_TOKENS=<merchant_id>:<运行时输入>
   AI_EDIT_WORKER_EXE=<释放目录>\worker\ai_edit_worker.exe
   AI_EDIT_FFMPEG_BINARY=<释放目录>\media\ffmpeg.exe
   AI_EDIT_FFPROBE_BINARY=<释放目录>\media\ffprobe.exe
   AI_EDIT_WORK_ROOT=%LOCALAPPDATA%\XiaogaoAI\TestData\<merchant_fp>\work
   AI_EDIT_STORAGE_ROOT=%LOCALAPPDATA%\XiaogaoAI\TestData\<merchant_fp>\materials
   ```

6. 启动内部 Local Agent 后轮询 `/health`，成功后显示“打开测试页面”和“停止测试服务”。
7. 正常退出用现有 Windows `taskkill /PID <owned pid> /T /F` 方式清理本次进程树。

- [ ] **Step 3：阻断 Worker 继承凭据**

在 `app/local_agent_main.py` 提取最小 `_build_ai_edit_worker_env()`，Worker Popen 显式传 `env=`；只保留 Windows 必需项和 FFmpeg/ffprobe 路径。补一个单测证明 token、9000 URL、数据库 URL 和 internal token 均不在 Worker 环境。

- [ ] **Step 4：绿灯与提交**

```powershell
& $Python310Exe -m pytest -q `
  tests/test_phase12_task11_launcher.py `
  tests/test_phase12_local_ai_edit_supervisor.py `
  tests/test_local_agent_auth.py `
  tests/test_phase12_local_ai_edit_routes.py
git diff --check -- app/phase12_test_launcher.py app/local_agent_main.py tests/test_phase12_task11_launcher.py tests/test_phase12_local_ai_edit_supervisor.py
git add -- app/phase12_test_launcher.py app/local_agent_main.py tests/test_phase12_task11_launcher.py tests/test_phase12_local_ai_edit_supervisor.py
git commit -m "功能：增加单入口测试启动器"
```

## 6. Task 11-2：轻量双运行时构建

**Files:**

- Create: `local_agent_phase12_test.spec`
- Create: `ai_edit_worker_phase12_test.spec`
- Create: `phase12_test_launcher.spec`
- Create: `requirements-phase12-test-worker.txt`
- Create: `scripts/build_phase12_test_payload.ps1`
- Create: `scripts/generate_phase12_test_payload.py`
- Create: `scripts/build_phase12_single_test_exe.ps1`
- Create: `tests/test_phase12_task11_packaging_contract.py`
- Create: `docs/ai/13_ai_edit/TEST_BUILD_NOTICE_TEMPLATE.md`

- [ ] **Step 1：冻结轻量构建合同**

测试只断言：

```text
两个测试 spec 与正式 spec 分离
Worker 使用 Python 3.11
测试 spec 显式 excludes 未批准模型/OCR 依赖
测试 Worker 不引用 requirements-ai-edit-worker.txt
构建输出使用独立 build/phase12-task11 与 dist/phase12-task11-delivery
最终目录精确两个文件
构建脚本不使用 Customer 模式和 LICENSE_CONFIRMED.txt
```

- [ ] **Step 2：实现测试 payload 构建**

1. Local Agent 使用现有 Python 3.10 环境和独立测试 spec。
2. Worker 使用 Python 3.11，仅要求：

   ```text
   pydantic==2.13.4
   pyinstaller==6.20.0
   ```

3. 复制 Local Agent、Worker、FFmpeg、ffprobe、`THIRD_PARTY_NOTICES.md`、GPL 文本、源码获取说明和测试说明到 payload。
4. 不复制模型、字体、`.env`、token 或现有 `dist/local-agent`。
5. `generate_phase12_test_payload.py` 按文件相对路径升序生成逐文件 SHA-256 清单。
6. 外层 PyInstaller onefile 只内嵌该 payload，输出名固定 `小高AI系统测试版.exe`。
7. 生成同名 SHA-256 文本并断言 delivery 目录精确两文件。

- [ ] **Step 3：合同绿灯与提交**

```powershell
& $Python310Exe -m pytest -q tests/test_phase12_task11_packaging_contract.py tests/test_phase12_ai_edit_packaging_contract.py
git diff --check -- `
  local_agent_phase12_test.spec `
  ai_edit_worker_phase12_test.spec `
  phase12_test_launcher.spec `
  requirements-phase12-test-worker.txt `
  scripts/build_phase12_test_payload.ps1 `
  scripts/generate_phase12_test_payload.py `
  scripts/build_phase12_single_test_exe.ps1 `
  tests/test_phase12_task11_packaging_contract.py
git add -- `
  local_agent_phase12_test.spec `
  ai_edit_worker_phase12_test.spec `
  phase12_test_launcher.spec `
  requirements-phase12-test-worker.txt `
  scripts/build_phase12_test_payload.ps1 `
  scripts/generate_phase12_test_payload.py `
  scripts/build_phase12_single_test_exe.ps1 `
  tests/test_phase12_task11_packaging_contract.py `
  docs/ai/13_ai_edit/TEST_BUILD_NOTICE_TEMPLATE.md
git commit -m "构建：增加单入口测试 EXE 轻量构建链"
```

## 7. Task 11-3：真实构建与一次总验收

- [ ] **Step 1：构建**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_phase12_single_test_exe.ps1 `
  -Python310Exe 'C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe' `
  -Python311Exe 'C:\Users\A\miniconda3\envs\zws\python.exe' `
  -FfmpegDir $FfmpegDir `
  -TestApiUrl $TestApiUrl `
  -TestFrontendUrl $TestFrontendUrl `
  -MerchantId $MerchantId
```

构建参数不得包含 token。若 Python 3.11 缺 PyInstaller，只安装固定 `pyinstaller==6.20.0`，不安装正式 Worker 重依赖。

- [ ] **Step 2：真实合成媒体 smoke**

使用随包 FFmpeg `lavfi color + sine` 生成 3 秒 MP4，启动打包后的 Worker 真子进程，验证：

```text
result.json=succeeded
720P/1080P 文件存在且非空
ffprobe 时长>0、分辨率正确、有音频
源文件 SHA-256 不变
取消后 Worker/FFmpeg 进程退出
```

- [ ] **Step 3：非生产联调**

使用专用测试账号、测试 token 和合成媒体，验证：

```text
启动器→19000 /health
前端→19000 鉴权
素材导入后 9000 可见
创建任务→真实 Worker→9000 终态
取消、重试、重启恢复各一次
生产/宝塔/真实模型/抖音发布调用为 0
```

不使用客户真实素材，不要求 WFP/ETW 取证；以测试环境访问日志、Local Agent 日志和任务状态作为联调证据。

- [ ] **Step 4：基础分发检查**

```text
payload 无模型权重、.env、token、LICENSE_CONFIRMED.txt
FFmpeg -L/-version/-buildconf 已保存
GPL 文本和源码获取说明已内嵌
最终目录精确两个文件
SHA-256 文本与 EXE 一致
```

Windows Defender 可用时执行一次文件扫描并记录结果；不可用不阻塞测试交付，但必须在报告中说明。

- [ ] **Step 5：回归与文档收口**

```powershell
& $Python310Exe -m pytest -q `
  tests/test_phase12_task11_launcher.py `
  tests/test_phase12_task11_packaging_contract.py `
  tests/test_phase12_ai_edit_worker_contract.py `
  tests/test_phase12_ai_edit_pipeline.py `
  tests/test_phase12_local_ai_edit_supervisor.py `
  tests/test_phase12_local_ai_edit_routes.py `
  tests/test_local_agent_auth.py
```

更新：

```text
docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md
docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md
docs/ai/05_PROJECT_CONTEXT.md
docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md
```

报告固定回传：提交链、EXE SHA-256、测试结果、真实 FFmpeg/Worker 次数、非生产联调结果、最终目录、已知缺失能力和未签名 SmartScreen 风险。

## 8. 唯一硬暂停点

Task 11-1~11-3 连续执行。构建完成后状态为：

```text
BUILT_PENDING_CUSTOMER_SEND_APPROVAL
```

执行窗口在此硬暂停。当前窗口只做一次最终快速审查；通过后改为：

```text
APPROVED_FOR_CUSTOMER_TEST_DELIVERY
```

未经最终批准不得发送甲方，但不再设置 D0/D1 中间检查点。
