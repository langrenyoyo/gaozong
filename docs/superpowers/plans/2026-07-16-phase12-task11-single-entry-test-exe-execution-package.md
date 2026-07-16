# Phase 12 Task 11 单入口测试 EXE Implementation Plan

> **执行窗口：** 使用 `executing-plans` 直接完成本计划，不设中间检查点。

**目标：** 构建甲方只需双击一次的 `小高AI系统测试版.exe`。

**架构：** 复用现有 Python 3.10 Local Agent、Python 3.11 Worker 和 `ai_edit_worker.spec`。外层 PyInstaller 单文件在运行时使用自身临时目录提供内部 Local Agent、Worker、FFmpeg 和 ffprobe，不再实现自定义 payload 清单、版本释放器或许可证门禁。

**技术栈：** Python 3.10/3.11、现有 PyInstaller、PowerShell、FFmpeg/ffprobe。

---

**状态：** `BUILT_LOCAL_SMOKE_ONLY`

**阻断：** `test_endpoint_config_placeholder`。当前 EXE 烘焙的是 `https://test-api.example.com` / `https://test.example.com`，仅能证明本地打包与媒体链，不能用于甲方业务测试。

## 1. 最终交付

最终只交付：

```text
小高AI系统测试版.exe
```

SHA-256 写入构建报告，不再生成第二个交付文件。

## 2. 当前决定

以下内容全部不作为 Task 11 开发、构建或交付阻断条件：

```text
许可证确认文件
第三方组件逐项清单
FFmpeg -L/-buildconf 审计
Defender/WFP/ETW
固定 PyInstaller/Pydantic 版本
双遍构建与可复现指纹
自定义 payload manifest
专用 worktree
中间检查点与发送前审批
```

不新增安装器、自动更新、卸载器或系统服务。

仅保留运行安全边界：

1. token 运行时输入，不进入源码、Git、日志、命令行或 EXE。
2. 19000 只监听 `127.0.0.1`，鉴权保持开启。
3. Worker 不继承 Local Agent token、数据库地址或 internal token。
4. 本轮不启动宝塔、生产数据库、真实付费模型或抖音发布。

## 3. 最小文件范围

```text
app/phase12_test_launcher.py
app/local_agent_main.py
local_agent_phase12_test.spec
phase12_test_launcher.spec
scripts/build_phase12_single_test_exe.ps1
tests/test_phase12_task11_launcher.py
docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md
docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md
docs/ai/05_PROJECT_CONTEXT.md
docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md
```

如真实构建证明还缺文件，可按根因增加；禁止顺手修改业务功能。

## 4. Task 11-1：单入口启动器

- [x] 新建 `app/phase12_test_launcher.py`，只用标准库完成：

  1. 从 `sys._MEIPASS` 定位内部 Local Agent、Worker、FFmpeg 和 ffprobe。
  2. 用 `tkinter` 掩码框读取 token，不落盘。
  3. 启动内部 Local Agent，注入 127.0.0.1、19000、测试 API、Worker 和媒体工具路径。
  4. `/health` 就绪后打开测试页面。
  5. 关闭启动器时终止自己启动的进程树。
  6. 端口已占用时明确提示，不杀未知进程。

- [x] 在 `app/local_agent_main.py` 复用现有 Worker 启动点，给 Worker 显式最小环境，去掉 token、9000 地址、数据库地址和 internal token。

- [x] 新建一个测试文件，只验证 token 不泄露、Worker 环境隔离和端口占用三条安全边界。

运行：

```powershell
$Python310Exe = 'C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe'
& $Python310Exe -m pytest -q tests/test_phase12_task11_launcher.py tests/test_local_agent_auth.py
```

提交：

```powershell
git add -- app/phase12_test_launcher.py app/local_agent_main.py tests/test_phase12_task11_launcher.py
git commit -m "功能：增加单入口测试启动器"
```

## 5. Task 11-2：直接构建单文件

- [x] 新建轻量 Local Agent spec，排除当前测试不使用的 OCR/模型重依赖。
- [x] 直接复用现有 `ai_edit_worker.spec` 构建 Python 3.11 Worker。
- [x] 新建外层 `phase12_test_launcher.spec`，把内部 Local Agent、Worker、FFmpeg 和 ffprobe 收进一个 onefile EXE。
- [x] 新建 `scripts/build_phase12_single_test_exe.ps1`：

  1. 使用现有 Python 3.10 和 3.11 环境。
  2. 缺 PyInstaller 时直接安装，不锁版本。
  3. 不读取 `LICENSE_CONFIRMED.txt` 或 `THIRD_PARTY_NOTICES.md`。
  4. 不执行许可证、Defender、archive 或 FFmpeg buildconf 检查。
  5. 输出 `dist/phase12-task11/小高AI系统测试版.exe`。
  6. 控制台打印 EXE SHA-256。

构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_phase12_single_test_exe.ps1 `
  -Python310Exe 'C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe' `
  -Python311Exe 'C:\Users\A\miniconda3\envs\zws\python.exe' `
  -FfmpegDir $FfmpegDir `
  -TestApiUrl $TestApiUrl `
  -TestFrontendUrl $TestFrontendUrl `
  -MerchantId $MerchantId
```

提交：

```powershell
git add -- local_agent_phase12_test.spec phase12_test_launcher.spec scripts/build_phase12_single_test_exe.ps1
git commit -m "构建：生成单入口 AI 剪辑测试 EXE"
```

## 6. Task 11-3：最小真实 smoke

- [x] 双击最终 EXE，验证 19000 `/health` 可用且鉴权开启。
- [x] 用随包 FFmpeg 合成 3 秒视频，启动打包后的真实 Worker，验证 720P/1080P 文件可被 ffprobe 读取且有音频。
- [x] 验证关闭外层 EXE 后，本次 Local Agent、Worker 和 FFmpeg 进程均退出。
- [x] 运行现有相邻回归：

```powershell
& $Python310Exe -m pytest -q `
  tests/test_phase12_task11_launcher.py `
  tests/test_phase12_ai_edit_worker_contract.py `
  tests/test_phase12_ai_edit_pipeline.py `
  tests/test_phase12_local_ai_edit_supervisor.py `
  tests/test_phase12_local_ai_edit_routes.py `
  tests/test_local_agent_auth.py
```

- [x] 更新 Task 11 报告与当前状态，记录 EXE 路径、SHA-256、真实 smoke 结果和当前缺失能力。

本地 smoke 完成状态：

```text
BUILT_LOCAL_SMOKE_ONLY
```

提供真实测试 API、前端地址和商户 ID 后重新构建，确认 EXE 烘焙配置正确并在干净 Windows 电脑启动，才可更新为 `BUILT_FOR_CUSTOMER_TEST`。不再等待许可证审查；Phase 13 与宝塔生产验证仍不启动。
