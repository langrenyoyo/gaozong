# Phase 12 Task 11 甲方测试专用单入口 EXE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 每个检查点必须硬暂停，不得自行越过。

**Goal:** 构建只供甲方授权测试电脑使用的单入口 `小高AI系统测试版.exe`，在不关闭鉴权、不合并 Python 运行时、不包含未核清模型依赖的前提下，释放并管理内部 Local Agent 与 AI 剪辑 Worker。

**Architecture:** 外层启动器使用 Python 3.10 标准库与 PyInstaller 单文件模式，只负责载荷校验、版本化原子释放、测试令牌校验和进程生命周期。精确批准的非生产 API/前端地址作为非秘密构建档案进入受哈希保护的运行配置，用户不能改填任意地址；商户 ID 由非生产 9000 根据输入 token 返回，不能自报。外层控制进程之外，内部 Local Agent 继续使用 Python 3.10 独立业务子进程，AI 剪辑 Worker 继续使用 Python 3.11 按任务启动的独立业务子进程；不得把两者合并。token 只通过 Local Agent 子进程环境传递，Worker 不继承且 token 不落盘。

**Tech Stack:** Python 3.10/3.11、PyInstaller 6.20.0、PowerShell、FFmpeg/ffprobe、pytest、Windows 本机回环网络。

---

## 0. 执行状态与审批边界

```text
计划基线：e4adddf
Phase 12：DONE_WITH_CONCERNS
唯一 concern：baota_ai_edit_production_not_verified
Task 11：APPROVED_FOR_TASK_11_0_1_ONLY
Phase 13：NOT_STARTED
正式客户安装包：NOT_BUILT
宝塔生产验证：NOT_STARTED，Phase 13 完成后统一执行
```

当前窗口只负责执行包、审查与审批；执行窗口负责实现和构建。

首批只批准执行 **Task 11-0 与 Task 11-1**。Task 11-1 红灯合同回传后，当前窗口完成检查点 D0 审查；未收到 D0 PASS 前不得进入 Task 11-2。

状态转换由当前审查窗口负责原位更新 `05_PROJECT_CONTEXT.md`、Phase 12 设计、`THIRD_PARTY_NOTICES.md`、主执行包、本 Task 11 执行包和 Task 11 报告，执行窗口不得自行宣告 PASS：

| 时点 | 允许状态 |
|---|---|
| 本计划批准 | `APPROVED_FOR_TASK_11_0_1_ONLY` |
| D0 | `CHECKPOINT_D0_BLOCKED` / `APPROVED_FOR_TASK_11_2` |
| D1 | `CHECKPOINT_D1_BLOCKED` / `APPROVED_FOR_TASK_11_3_5` |
| 构建与 smoke | `BUILT_PENDING_APPROVAL` / `BLOCKED_BY_DISTRIBUTION_EVIDENCE` / `BLOCKED_BY_BUILD_OR_SMOKE` |
| D2 | `APPROVED_FOR_CUSTOMER_TEST_DELIVERY` / 上述阻断状态 |

## 1. 阶段目标、允许范围、禁止事项、验收标准

### 1.1 本阶段目标

1. 最终甲方交付目录只有：

   ```text
   小高AI系统测试版.exe
   小高AI系统测试版.exe.sha256.txt
   ```

2. 用户只启动外层 EXE，不手工启动内部第二个 EXE。
3. 外层启动器是生命周期控制进程；内部仍是 Local Agent Python 3.10 与 Worker Python 3.11 两个独立业务运行时、两个独立业务子进程。Worker 仅在任务期间存在，因此运行时总进程数不是“只有两个”。
4. 启动器先校验内嵌载荷 SHA-256，再原子释放到：

   ```text
   %LOCALAPPDATA%\XiaogaoAI\Test\<version>\
   ```

5. 测试数据使用独立目录，不复用既有微信助手目录：

   ```text
   %LOCALAPPDATA%\XiaogaoAI\TestData\<merchant_fp>\
   ```

6. 甲方可验证素材导入、任务创建、基础区间裁剪、Vid.Stab、720P/1080P、取消、恢复和状态回写。未实现的 ASR、视觉标签、空镜智能匹配必须明确显示为缺失能力，禁止伪造成功。
7. 测试页面仍由精确批准的非生产前端 URL 提供；Task 11 EXE 只承载浏览器所在电脑的本机 19000 与 Worker，不内嵌 9000、9100、数据库或前端站点。非生产 URL 是非秘密构建档案并受 payload 哈希保护；匹配 token 由安全渠道另行提供，不进入交付文件。

### 1.2 允许修改范围

执行窗口仅可按任务白名单修改以下文件；新增同名 FIX 任务时也不得扩大到 Phase 13：

```text
app/phase12_test_launcher.py
app/local_agent_main.py
app/routers/ai_edit.py
local_agent_phase12_test.spec
ai_edit_worker_phase12_test.spec
phase12_test_launcher.spec
requirements-phase12-test-worker.txt
scripts/build_phase12_test_payload.ps1
scripts/build_phase12_single_test_exe.ps1
scripts/generate_phase12_test_payload.py
tests/test_phase12_task11_launcher.py
tests/test_phase12_task11_launcher_contract.py
tests/test_phase12_task11_packaging_contract.py
tests/test_phase12_task11_distribution_scan.py
tests/test_phase12_local_ai_edit_supervisor.py
tests/test_phase12_ai_edit_api.py
docs/ai/13_ai_edit/TEST_BUILD_NOTICE_TEMPLATE.md
docs/ai/13_ai_edit/THIRD_PARTY_NOTICES.md
docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md
docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md
docs/ai/05_PROJECT_CONTEXT.md
docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md
docs/superpowers/plans/2026-07-16-phase12-task11-single-entry-test-exe-execution-package.md
```

除已列出的 token 商户绑定端点、Local Agent CORS/无重定向/环境隔离根因修复外，不得修改其它业务运行代码；不得修改既有 `local_agent.spec`、`ai_edit_worker.spec` 或正式构建脚本。

### 1.3 禁止事项

1. 禁止构建或冒充正式客户安装包。
2. 禁止创建、伪造或临时提交 `LICENSE_CONFIRMED.txt`。
3. 禁止调用 `DistributionMode=Customer`。
4. 禁止包含 `ultralytics`、YOLO、FunASR、`open_clip`、`open-clip-torch`、对应模型权重及未确认字体。
5. 测试专用 Local Agent 也不得包含 EasyOCR、PyTorch、torchvision、OpenCV、Pillow 模型包；微信 OCR/自动化不属于本测试件验收范围。
6. 禁止关闭 19000 鉴权，禁止使用 `auth_required=false`、固定万能令牌或匿名路由。
7. 禁止把商户令牌写入源码、构建参数、构建日志、载荷清单、测试说明、报告、Git 历史或最终 EXE。
8. 禁止连接 `callback.misanduo.com`、宝塔、生产数据库、真实付费模型、Milvus 或抖音发布接口。D2 只允许访问运行档案中精确批准的非生产前端与 9000 API，并逐主机计数。
9. 禁止把 Python 3.10 与 3.11 合并成一个运行时或把 Worker 改成 Local Agent 进程内函数调用。
10. 禁止自动清理旧版本、自动更新、注册表安装、系统服务、自启动和安装程序；这些不属于 Task 11。
11. 禁止把现有 `dist/local-agent`、`build/` 陈旧内容直接复制进测试载荷。
12. 禁止在当前脏主工作区执行 Task 11。执行窗口必须从本计划提交创建独立 clean worktree；主工作区全部已有及并发改动一律不枚举、不暂存、不修改。

### 1.4 最终验收标准

1. 启动器载荷清单逐文件 SHA-256 校验通过；篡改任一字节必须拒绝启动。
2. 释放根通过 Windows Known Folder API 获取；不可由命令行、环境变量或用户输入任意指定。路径穿越、绝对路径、符号链接、junction/重解析点、额外文件和额外目录均拒绝。
3. 版本包含 Git 提交与 payload 内容指纹；已存在且闭集校验完整的同版本目录只读复用，已存在但不完整时失败，不覆盖、不自动删除。
4. 用户只输入 token；商户 ID 必须由精确允许的非生产 9000 token-context 端点返回并绑定。token 只存在于启动器内存和 Local Agent 子进程环境，输入框掩码显示，日志与异常不回显。
   Local Agent 启动 Worker 时必须使用最小环境白名单，Worker 不得继承 `LOCAL_AGENT_TOKEN(S)`、9000 地址或其它服务凭据。
5. 19000 只监听 `127.0.0.1:19000`；端口被占用时不启动、不杀未知进程。
6. 正常或异常退出时通过持有的 Windows Job Object/进程句柄终止本次 Local Agent/Worker；禁止仅凭 PID 数字杀进程，不影响既有微信助手或其他版本。
7. Worker 使用真实打包后的 Python 3.11 EXE 和随包 FFmpeg/ffprobe 完成合成媒体 720P/1080P smoke。
8. 单元/构建/离线媒体 smoke 的网络调用为 0；D2 非生产端到端只允许档案中的前端与 9000 主机并记录调用，所有生产、宝塔、真实模型、Milvus 与抖音发布调用为 0。
9. 最终交付目录精确两文件，SHA-256 文本与实际 EXE 一致。
10. 四方总验收未 PASS 前按状态表停在 `BUILT_PENDING_APPROVAL`、`BLOCKED_BY_DISTRIBUTION_EVIDENCE` 或 `BLOCKED_BY_BUILD_OR_SMOKE`，不得发送甲方。
11. 对外交付审批还必须确认运行档案中的非生产前端/API 可达，9000 已配置专用短期 token，测试窗口结束时间和撤销负责人已登记；token 值只能通过安全渠道提供，窗口结束后必须撤销。

## 2. 文件职责冻结

| 文件 | 单一职责 |
|---|---|
| `app/phase12_test_launcher.py` | 载荷校验、原子释放、运行时输入、环境构造、Local Agent 生命周期 |
| `local_agent_phase12_test.spec` | AI 剪辑测试专用 Local Agent 轻量打包，显式排除 OCR/模型重依赖 |
| `ai_edit_worker_phase12_test.spec` | 测试专用 Worker 打包，显式排除 ASR/视觉模型依赖 |
| `phase12_test_launcher.spec` | 把已生成并校验的 payload 收进单入口 onefile |
| `requirements-phase12-test-worker.txt` | Worker 测试构建的最小锁定依赖 |
| `scripts/build_phase12_test_payload.ps1` | 隔离构建两个内部运行时并组装 payload |
| `scripts/generate_phase12_test_payload.py` | 生成测试说明和逐文件 SHA-256 载荷清单 |
| `scripts/build_phase12_single_test_exe.ps1` | 清洁构建、组合 onefile、最终扫描、生成外层 SHA-256 |
| `app/routers/ai_edit.py` | 提供 Local Agent token 到权威 merchant_id 的只读绑定确认端点 |
| `app/local_agent_main.py` | 精确 CORS、无重定向 HTTP、Local Agent/Worker 最小环境与安全 cwd |
| `tests/test_phase12_task11_launcher.py` | 启动器纯逻辑与进程边界单测 |
| `tests/test_phase12_task11_launcher_contract.py` | 启动器静态安全合同 |
| `tests/test_phase12_task11_packaging_contract.py` | 双运行时、单入口、构建模式与最终目录合同 |
| `tests/test_phase12_task11_distribution_scan.py` | 禁止依赖、权重、密钥和正式分发门禁扫描 |
| `docs/ai/13_ai_edit/TEST_BUILD_NOTICE_TEMPLATE.md` | 构建时生成内部测试说明的固定模板 |
| `docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md` | Task 11 当前事实、证据与审批状态 |

## 3. Task 11-0：基线、环境与分发证据预检

**风险级别：HIGH**，涉及构建、文件分发、凭证边界和本机进程。

**Required sub-skill:** `using-git-worktrees`。

**Files:**
- Create: `docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md`
- Modify: none

- [ ] **Step 1: 从计划提交创建独立 clean worktree**

运行：

```powershell
$MainRepo = (Resolve-Path 'E:\work\project\auto_wechat').Path
$Worktree = 'E:\work\project\auto_wechat\.worktrees\phase12-task11'
$ApprovedTask11Commit = '<当前审查窗口最终批准回传的精确提交 SHA>'
git -C $MainRepo status --short
if (Test-Path -LiteralPath $Worktree) { throw "Task 11 worktree 已存在，禁止复用未知目录" }
git -C $MainRepo cat-file -e "$ApprovedTask11Commit^{commit}"
git -C $MainRepo worktree add -b phase12-task11 $Worktree $ApprovedTask11Commit
Set-Location $Worktree
if ((git rev-parse HEAD) -ne $ApprovedTask11Commit) { throw 'Task 11 worktree 未绑定批准提交' }
git status --porcelain
git diff --check
```

期望：`ApprovedTask11Commit` 必须逐字取自当前窗口最终回传，禁止改用当时可变的 `HEAD`；主工作区只读记录其全部脏状态；新 worktree 基于该不可变批准提交，`git status --porcelain` 为空且 `git diff --check` 通过。后续所有 Task 11 编辑、测试、构建与提交只在该 worktree；不得在主工作区执行。后续构建脚本验证该提交是当前 Task 11 HEAD 的祖先。

- [ ] **Step 2: 验证双运行时与构建工具**

运行：

```powershell
$Python310Exe = 'C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe'
$Python311Exe = 'C:\Users\A\miniconda3\envs\zws\python.exe'
& $Python310Exe -c "import sys,PyInstaller,pydantic; print(sys.version); print(PyInstaller.__version__); print(pydantic.__version__)"
& $Python311Exe -c "import sys,pydantic,importlib.util; print(sys.version); print(pydantic.__version__); print(bool(importlib.util.find_spec('PyInstaller')))"
```

固定要求：Local Agent 为 Python 3.10.x；Worker 为 Python 3.11.x；PyInstaller 固定 `6.20.0`。若 Worker 环境缺 PyInstaller，只记录 `BUILD_ENV_BLOCKED_PYINSTALLER`，未经用户允许不得静默升级其它包。

- [ ] **Step 3: 记录 FFmpeg 可分发证据**

对执行人明确提供的 `FfmpegDir` 运行：

```powershell
& "$FfmpegDir\ffmpeg.exe" -version
& "$FfmpegDir\ffmpeg.exe" -L
& "$FfmpegDir\ffmpeg.exe" -buildconf
& "$FfmpegDir\ffmpeg.exe" -filters | Select-String 'vidstabdetect|vidstabtransform'
```

门禁：

- 缺 `ffmpeg.exe`/`ffprobe.exe`/Vid.Stab：BLOCKED。
- 构建参数含 `--enable-nonfree`：`BLOCKED_BY_DISTRIBUTION_EVIDENCE`。
- `-buildconf` 中每个 `--enable-lib*` 外部组件必须进入独立 FFmpeg 组件许可证映射；未知项或缺证据即阻断。优先使用仅含项目所需编码/封装/Vid.Stab 组件的可枚举最小 GPL 构建，不能因为是 Gyan full build 就默认放行。
- 无实际构建对应的 GPL 文本、`-L/-version/-buildconf`、构建来源或源码获取说明：`BLOCKED_BY_DISTRIBUTION_EVIDENCE`。
- 不得把“开源”本身当作可分发证据。

- [ ] **Step 4: 冻结非生产联调运行档案**

执行人必须从审批人处取得两个非秘密值，不得自行猜测：

```text
approved_test_api_base_url=https://<精确非生产9000主机及基路径>
approved_test_frontend_origin=https://<精确非生产前端origin>
```

两者必须是 HTTPS、无用户名密码/query/fragment，且不属于 `callback.misanduo.com` 或任何生产别名。Task 11-0 只验证格式和审批记录，不连接网络；缺任一值或非生产归属证据即 `CHECKPOINT_D0_BLOCKED`。token 不属于运行档案，不在本步骤收集。

- [ ] **Step 5: 证明现有 Worker 正式构建链不可复用**

运行：

```powershell
rg -n "funasr|ultralytics|open-clip|torch" requirements-ai-edit-worker.txt scripts/build_ai_edit_worker_exe.ps1
rg -n "DistributionMode|Customer|LICENSE_CONFIRMED|ModelDir" scripts/build_ai_edit_worker_exe.ps1
```

期望：命中并写入报告，结论为“Task 11 必须使用独立测试构建 spec/脚本，不得调用正式 Customer 模式”。

- [ ] **Step 6: 新建预检报告并提交**

报告必须原位包含：计划提交、独立 worktree clean 证据、Python/PyInstaller 版本、FFmpeg `-L/-version/-buildconf` 摘要、分发证据状态、批准的非生产 API/frontend 主机、网络调用数 0 和下一门禁。不得记录绝对用户目录、令牌或许可证文件私有来源路径。

```powershell
git add -- docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md
git diff --cached --check
git commit -m "文档：记录 Task 11 测试 EXE 构建预检"
```

若分发证据不足，提交报告后硬暂停，状态为 `BLOCKED_BY_DISTRIBUTION_EVIDENCE`；运行档案不完整则状态为 `CHECKPOINT_D0_BLOCKED`。两者均不得继续 Task 11-1。

## 4. Task 11-1：冻结单入口、安全和分发合同红灯

**Files:**
- Create: `tests/test_phase12_task11_launcher_contract.py`
- Create: `tests/test_phase12_task11_packaging_contract.py`
- Create: `tests/test_phase12_task11_distribution_scan.py`
- Modify: `docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md`

- [ ] **Step 1: 编写启动器静态合同红灯**

至少冻结以下断言：

```python
def test_launcher_contract_files_exist(): ...
def test_launcher_uses_windows_known_folder_version_root(): ...
def test_launcher_has_payload_schema_and_sha256_verification(): ...
def test_launcher_rejects_absolute_traversal_symlink_junction_and_extra_entries(): ...
def test_launcher_uses_staging_then_os_replace(): ...
def test_launcher_does_not_accept_arbitrary_release_root_from_cli_or_env(): ...
def test_launcher_does_not_persist_local_agent_token(): ...
def test_launcher_keeps_loopback_and_auth_enabled(): ...
def test_launcher_accepts_only_hashed_nonproduction_runtime_profile(): ...
def test_launcher_has_verify_only_mode_without_business_routes(): ...
def test_launcher_uses_job_handle_not_pid_only_cleanup(): ...
def test_worker_process_contract_drops_local_agent_secrets(): ...
def test_local_agent_process_contract_uses_minimal_env_safe_cwd_and_exact_cors(): ...
def test_local_agent_http_contract_rejects_redirects(): ...
def test_agent_context_contract_derives_merchant_from_server_token(): ...
```

静态合同不得只搜索一个正向词；必须同时断言禁词不存在：`0.0.0.0`、`auth_required=false`、`LICENSE_CONFIRMED`、`DistributionMode=Customer`、令牌写文件代码、业务可写 `--offline-smoke`。扫描范围只限 Task 11 新增文件、测试 spec/脚本和实际 payload，不得因为既有正式构建链含模型依赖而制造假红灯。

- [ ] **Step 2: 编写打包合同红灯**

至少冻结：

```python
def test_test_specs_are_separate_from_formal_specs(): ...
def test_local_agent_test_spec_excludes_ocr_and_model_packages(): ...
def test_worker_test_spec_excludes_asr_and_visual_model_packages(): ...
def test_worker_test_requirements_are_minimal_and_exactly_pinned(): ...
def test_payload_builder_uses_isolated_output_root(): ...
def test_payload_builder_never_reads_dist_local_agent_as_input(): ...
def test_outer_spec_is_onefile_and_embeds_only_verified_payload(): ...
def test_delivery_directory_contract_is_exactly_exe_and_sha256(): ...
def test_build_script_never_uses_customer_mode_or_license_marker(): ...
def test_build_requires_clean_dedicated_worktree(): ...
def test_version_contains_git_and_payload_fingerprint(): ...
def test_same_commit_with_different_payload_gets_different_version(): ...
```

- [ ] **Step 3: 编写分发扫描红灯**

扫描必须分层，禁止裸子串扫描。模块根与发行物规范名固定为：

```python
FORBIDDEN_MODULE_ROOTS = {
    "funasr", "ultralytics", "yolo", "open_clip",
    "easyocr", "torch", "torchvision", "cv2", "PIL",
}
FORBIDDEN_DISTRIBUTIONS = {
    "funasr", "ultralytics", "open-clip-torch", "easyocr",
    "torch", "torchvision", "opencv-python", "pillow",
}
FORBIDDEN_WEIGHT_SUFFIXES = {".pt", ".pth", ".onnx", ".safetensors", ".ckpt"}
```

语义规则：

1. Task 11 Python 源码用 `ast` 只检查 `Import/ImportFrom` 的精确模块根。
2. spec 用 `ast` 解析；禁用名允许且必须出现在 `excludes`，但不得出现在 `hiddenimports`、`collect_all` 或 datas/binaries 来源。
3. requirements 按 PEP 503 规范化发行物名精确比较。
4. PyInstaller archive 按条目模块根精确比较；例如 `compileall` 不得因包含 `pil` 字符被误判。
5. 实际 payload 路径、archive 与依赖清单要求禁入集合零命中；测试常量、阻断消息和许可证说明不参与零命中计数。

测试还必须拒绝：

- `LICENSE_CONFIRMED.txt`
- `.env`、`LOCAL_AGENT_TOKEN=`、`LOCAL_AGENT_TOKENS=` 出现在 payload
- FFmpeg `--enable-nonfree`
- 最终目录多出说明文件、日志、目录或第二个 EXE

- [ ] **Step 4: 运行红灯并保存精确失败**

```powershell
& $Python310Exe -m pytest -q `
  tests/test_phase12_task11_launcher_contract.py `
  tests/test_phase12_task11_packaging_contract.py `
  tests/test_phase12_task11_distribution_scan.py
```

期望：因 Task 11 实现文件不存在而 FAIL；不得出现 collection error，不得因为测试自身语法错误而红。

- [ ] **Step 5: 提交红灯合同并硬暂停**

```powershell
git add -- `
  tests/test_phase12_task11_launcher_contract.py `
  tests/test_phase12_task11_packaging_contract.py `
  tests/test_phase12_task11_distribution_scan.py `
  docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md
git diff --cached --check
git commit -m "测试：冻结 Task 11 单入口测试 EXE 合同"
```

### 检查点 D0：合同冻结复审

当前窗口执行 Spec Reviewer、Security Reviewer、Distribution Reviewer 三方复审：

1. 红灯是否真实证明缺实现，而不是测试写错。
2. 单入口是否仍保持双运行时和双进程。
3. 运行时令牌是否不落盘、不入包、不入日志。
4. 测试包是否排除全部未核清模型和 OCR 重依赖。
5. 最终两文件合同是否与用户确认一致。
6. 正式安装包、Phase 13、宝塔是否保持未启动。

三方全 PASS 后，当前窗口原位更新 6 份权威文档并提交 `APPROVED_FOR_TASK_11_2`；任一 Must-Fix 则写 `CHECKPOINT_D0_BLOCKED`。完成状态提交后才可批准 Task 11-2。

## 5. Task 11-2：实现最小启动器与安全释放

**Files:**
- Create: `app/phase12_test_launcher.py`
- Create: `tests/test_phase12_task11_launcher.py`
- Modify: `app/local_agent_main.py`
- Modify: `app/routers/ai_edit.py`
- Modify: `tests/test_phase12_local_ai_edit_supervisor.py`
- Modify: `tests/test_phase12_ai_edit_api.py`
- Modify: `tests/test_phase12_task11_launcher_contract.py`
- Modify: `docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md`

- [ ] **Step 1: 为纯逻辑写红灯单测**

启动器对外函数签名冻结为：

```python
@dataclass(frozen=True)
class RuntimeProfile:
    api_base_url: str
    frontend_origin: str

@dataclass(frozen=True)
class RuntimeInput:
    token: str

def validate_runtime_profile(value: RuntimeProfile) -> RuntimeProfile: ...
def validate_runtime_input(value: RuntimeInput) -> RuntimeInput: ...
def fetch_agent_context(profile: RuntimeProfile, token: str) -> str: ...
def load_payload_manifest(payload_root: Path) -> dict: ...
def verify_payload_tree(payload_root: Path, manifest: dict) -> None: ...
def release_payload(version: str, payload_root: Path, *, local_appdata: Path | None = None) -> Path: ...
def get_local_appdata_known_folder() -> Path: ...
def build_local_agent_env(profile: RuntimeProfile, token: str, merchant_id: str, release_root: Path, data_root: Path) -> dict[str, str]: ...
def create_kill_on_close_job() -> object: ...
def assign_process_to_job(job: object, process: subprocess.Popen) -> None: ...
def terminate_owned_job(job: object, process: subprocess.Popen) -> None: ...
```

覆盖：清单 schema、重复 path、大小/哈希不符、绝对路径、`..`、反斜杠、隐藏段、符号链接/junction/其它重解析点、额外文件/目录、版本段、已存在完整版本复用、已存在损坏版本拒绝、原子释放失败清理 staging、Known Folder、运行档案精确 URL、30x 拒绝、token→merchant 绑定、令牌空白拒绝、Local Agent/Worker 最小环境、固定 cwd 和无令牌写盘。

- [ ] **Step 2: 实现清单校验和原子释放**

载荷清单固定结构：

```json
{
  "schema_version": "phase12_test_payload_v1",
  "version": "phase12-task11-0123456789ab-a1b2c3d4e5f60708",
  "git_commit": "0123456789abcdef0123456789abcdef01234567",
  "payload_fingerprint": "a1b2c3d4e5f60708",
  "files": [
    {"path": "local-agent/小高AI微信助手.exe", "size": 1, "sha256": "64位小写十六进制"}
  ]
}
```

实现约束：

1. 清单字段严格，未知字段拒绝。
2. 版本严格匹配 `phase12-task11-[0-9a-f]{12}-[0-9a-f]{16}`。唯一算法见 Task 11-4：对不含生成后 manifest/notice 的最终 payload 闭集、notice 模板 SHA-256 和固定 schema 生成唯一规范 JSON，再取 SHA-256 前 16 位；工具链产出的二进制和构建证据本身已在 payload 中参与哈希，不另设第二套工具链指纹。同提交不同载荷必须得到不同版本。
3. 路径只允许 `/` 分隔的普通相对段。源、staging、目标及其从 Known Folder 起的全部父级不得带 Windows `FILE_ATTRIBUTE_REPARSE_POINT`。
4. 闭集校验：实际文件集合必须精确等于 `manifest files + payload_manifest.json`，实际目录集合必须精确等于这些路径隐含目录；任何额外 DLL、文件或目录都拒绝。
5. 复制前校验内嵌 payload，复制后再次校验 staging；manifest 复制字节必须与内嵌源一致。
6. staging 名使用同父目录随机后缀，成功后 `os.replace(staging, version_root)`。
7. 版本目录存在时只做相同闭集校验并复用；不覆盖、不删除。
8. 生产入口用 `SHGetKnownFolderPath(FOLDERID_LocalAppData)` 获取根，不信任 `LOCALAPPDATA` 环境值。`local_appdata` 只用于单测注入，命令行和环境变量不得暴露 release root 参数。

- [ ] **Step 3: 实现受保护运行档案与 token 商户绑定**

构建时生成的 `runtime_profile.json` 必须列入 payload manifest，只含 D0 批准的非生产 `api_base_url` 与 `frontend_origin`。启动器不提供地址输入框或覆盖参数。使用标准库 `tkinter` 只采集 Local Agent 测试 token，输入框必须 `show="*"`；窗口、异常、日志不得显示 token。

运行档案与绑定规则：

- 两个 URL 只允许 D0 精确值、HTTPS、无用户名密码/query/fragment；不得只靠拒绝一个生产域名。
- 在 `app/routers/ai_edit.py` 新增 `GET /ai-edit/agent-context`，复用 `require_local_agent_context`，只返回该 token 在 9000 权威映射的 `merchant_id`，响应 `Cache-Control: no-store`。
- 启动器使用 `ProxyHandler({}) + NoRedirectHandler` 和系统默认 TLS 校验直连该端点；任何代理、30x、主机变化、非 200、空 merchant 或响应结构漂移均失败，不启动 19000。
- 用户不输入 merchant_id；`LOCAL_AGENT_TOKENS` 的 merchant 只取权威响应。
- token 只允许 `[A-Za-z0-9_-]{24,256}`，禁止逗号、冒号、空白和换行。
- 正式交付 EXE 不包含 `--offline-smoke`。允许 `--verify-only`，但该模式只能完成 payload 校验/释放后退出，不启动 Local Agent、Worker 或任何业务路由。

- [ ] **Step 4: 构造隔离子进程环境**

必须设置：

```text
LOCAL_AGENT_HOST=127.0.0.1
LOCAL_AGENT_PORT=19000
LOCAL_AGENT_AUTH_REQUIRED=true
AUTO_WECHAT_SERVER_URL=<runtime_profile.api_base_url>
LOCAL_AGENT_TOKEN=<token，仅进环境>
LOCAL_AGENT_TOKENS=<server_merchant_id>:<token，仅进环境>
LOCAL_AGENT_ALLOWED_ORIGINS=<runtime_profile.frontend_origin>
AI_EDIT_WORKER_EXE=<release_root>\worker\ai_edit_worker.exe
AI_EDIT_FFMPEG_BINARY=<release_root>\media\ffmpeg.exe
AI_EDIT_FFPROBE_BINARY=<release_root>\media\ffprobe.exe
AI_EDIT_WORK_ROOT=<TestData merchant_fp>\work
AI_EDIT_STORAGE_ROOT=<TestData merchant_fp>\materials
LOCAL_AGENT_LOG_FILE=<TestData merchant_fp>\logs\local_agent.log
```

`AUTO_WECHAT_SERVER_URL` 必须来自 runtime profile，不再来自用户输入。`merchant_fp` 使用 `sha256(merchant_id)[:16]`，避免把商户 ID 直接写入路径。不得生成 `.env`。

启动器从空 dict 构造 Local Agent 最小环境，只复制 `SYSTEMROOT/WINDIR/TEMP/TMP/USERPROFILE`，重建 `PATH=<release media>;<SystemRoot>\System32`，再加入上列显式业务变量；不继承 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY`、数据库 URL、internal token 或开发机 `.env`。Local Agent `cwd` 固定为闭集校验后的 `release_root/local-agent`。

在 `app/local_agent_main.py`：

1. 提取 `_get_react_allowed_origins()`：未设置 `LOCAL_AGENT_ALLOWED_ORIGINS` 时保持既有来源列表不变；Task 11 设置后只接受 runtime profile 的单一 frontend origin，不合并默认生产来源或通配符。
2. `_http_get_json`、`_http_post_json`、DELETE 和 AI 编辑回写统一使用 `ProxyHandler({}) + NoRedirectHandler`，token 不得经过代理或跨源转发。
3. 提取 `_build_ai_edit_worker_env()`，Worker Popen 必须显式传 `env=` 与 `cwd=manifest_path.parent`。环境从空 dict 构造，只含 Windows 必需项与 `AI_EDIT_FFMPEG_BINARY/AI_EDIT_FFPROBE_BINARY`，明确不含 Local Agent token、9000 地址、数据库 URL、代理或 internal token。

- [ ] **Step 5: 实现进程生命周期**

1. 启动前探测 19000；被占用即显示稳定错误 `PORT_19000_IN_USE`，不杀进程。
2. 使用参数数组、`shell=False`、上一步最小环境和固定 cwd 启动内部 Local Agent。
3. 使用 Windows Job Object 并设置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`；Local Agent 启动后必须立即加入该 Job，加入失败则先终止子进程再失败退出。Worker 继承同一 Job，外层启动器异常退出或句柄关闭时由系统清理整棵子进程树。
4. 最多等待 30 秒轮询 `/health` 与 `/agent/version`；只访问回环地址。
5. 启动成功后显示最小状态窗口、“打开测试页面”和“停止测试服务”按钮；只有用户点击前者才用标准库 `webbrowser.open(runtime_profile.frontend_origin)` 打开精确批准的非生产前端根，不把 token/merchant 放入 URL。自动化 E2E 不点击该按钮，改用隔离 Playwright Chromium，避免既有浏览器流量污染网络证据。
6. 正常退出、窗口关闭、Ctrl+C 和启动失败都调用 `TerminateJobObject` 并关闭 Job/process handle。
7. 禁止 `taskkill /PID` 数字兜底；清理只依赖当前持有的 Job Object 与原始进程句柄，测试覆盖子进程已退出及 PID 复用场景。

- [ ] **Step 6: 运行绿灯与回归**

```powershell
& $Python310Exe -m pytest -q `
  tests/test_phase12_task11_launcher.py `
  tests/test_phase12_task11_launcher_contract.py `
  tests/test_phase12_local_ai_edit_supervisor.py `
  tests/test_phase12_ai_edit_api.py `
  tests/test_local_agent_auth.py `
  tests/test_phase12_local_ai_edit_routes.py
```

期望：全 PASS，真实网络和真实子进程调用为 0；进程测试全部替身。

- [ ] **Step 7: 提交并进入检查点 D1**

```powershell
git add -- `
  app/phase12_test_launcher.py `
  app/local_agent_main.py `
  app/routers/ai_edit.py `
  tests/test_phase12_task11_launcher.py `
  tests/test_phase12_task11_launcher_contract.py `
  tests/test_phase12_local_ai_edit_supervisor.py `
  tests/test_phase12_ai_edit_api.py `
  docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md
git diff --cached --check
git commit -m "功能：增加 Task 11 单入口测试启动器"
```

### 检查点 D1：启动器安全边界复审

Spec、Code Quality、Security 三方必须验证：Known Folder 与重解析点强门、闭集双重哈希、原子释放、token→merchant 权威绑定、精确 CORS/无重定向、Local Agent/Worker 最小环境与安全 cwd、端口占用不误杀、Job Object/进程句柄清理、无任意 release root。PASS 后，当前窗口原位更新 6 份权威文档并提交 `APPROVED_FOR_TASK_11_3_5`；任一 Must-Fix 则写 `CHECKPOINT_D1_BLOCKED`。

## 6. Task 11-3：构建许可安全的双运行时 payload

**Files:**
- Create: `local_agent_phase12_test.spec`
- Create: `ai_edit_worker_phase12_test.spec`
- Create: `requirements-phase12-test-worker.txt`
- Create: `scripts/build_phase12_test_payload.ps1`
- Create: `docs/ai/13_ai_edit/TEST_BUILD_NOTICE_TEMPLATE.md`
- Modify: `tests/test_phase12_task11_packaging_contract.py`
- Modify: `tests/test_phase12_task11_distribution_scan.py`
- Modify: `docs/ai/13_ai_edit/THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: 冻结最小 Worker 依赖**

文件内容只允许：

```text
pydantic==2.13.4
pyinstaller==6.20.0
```

不得引用 `requirements-ai-edit-worker.txt`。

Worker 构建环境当前缺 PyInstaller 时，D1 放行后只允许显式安装锁定版本：

```powershell
& $Python311Exe -m pip install --only-binary=:all: pyinstaller==6.20.0
```

该步骤可能访问 Python 包源，必须在报告中单列为“构建工具下载”，不得混入产品运行时零网络证明；不得顺带升级 Pydantic 或安装正式 Worker 重依赖。

- [ ] **Step 2: 新建测试专用 Local Agent spec**

入口仍是 `app/local_agent_exe_entry.py`，输出仍为内部 `小高AI微信助手.exe`，但显式排除：

```text
easyocr, torch, torchvision, cv2, opencv, PIL, pillow, funasr, ultralytics, open_clip
```

不得修改正式 `local_agent.spec`。构建后必须 smoke `/health`、`/agent/version` 和 `/agent/ai-edit/status`；微信 OCR 路由不在 Task 11 验收范围。

- [ ] **Step 3: 新建测试专用 Worker spec**

入口仍是 `apps/ai_edit/worker_main.py`，Python 固定 3.11，显式排除 ASR、视觉模型、服务端框架和 OCR 重依赖。只打包 Pydantic、Worker 合同、媒体管线和标准库。

- [ ] **Step 4: 实现隔离 payload 构建脚本**

参数固定为：

```powershell
param(
  [Parameter(Mandatory=$true)][string]$Python310Exe,
  [Parameter(Mandatory=$true)][string]$Python311Exe,
  [Parameter(Mandatory=$true)][string]$FfmpegDir,
  [Parameter(Mandatory=$true)][string]$ApprovedTestApiBaseUrl,
  [Parameter(Mandatory=$true)][string]$ApprovedTestFrontendOrigin,
  [Parameter(Mandatory=$true)][string]$OutputRoot
)
```

脚本必须：

1. 校验 Python 3.10/3.11 和 PyInstaller 6.20.0；两个 URL 必须与 Task 11-0 报告精确一致。
2. 解析 `OutputRoot`，只允许位于仓库 `build/phase12-task11/` 下。
3. 清理前再次校验绝对路径前缀，禁止删除仓库外或 `dist/local-agent`。
4. 分别使用两个 spec 和两个独立 workpath 构建。
5. 备份 `app/local_agent_build_info.py` 原始字节，在 `finally` 无条件恢复，构建后 `git diff -- app/local_agent_build_info.py` 必须为空。
6. 复制 FFmpeg/ffprobe 到 `payload/media/`；不得复制模型、字体、`.env` 或令牌。
7. 把 Local Agent 放入 `payload/local-agent/`，Worker 放入 `payload/worker/`。
8. 生成 `payload/runtime_profile.json`，只含批准的 API base URL 和 frontend origin；不得含 token/merchant_id。
9. 保存 `ffmpeg -L/-version/-buildconf` 为内部 `licenses/FFMPEG_BUILD_INFO.txt`；解析全部 `--enable-lib*` 并生成 `licenses/FFMPEG_COMPONENTS.json`，每项记录组件、版本、SPDX、许可证文件 SHA-256、源码 URL。映射集合必须与 buildconf 外部组件精确相等。
10. 复制对应 GPL、Python PSF、Tcl/Tk、PyInstaller bootloader exception 及实际打包依赖许可证文本；缺一项即 BLOCKED。
11. 保存 `build/phase12-task11/evidence/local-agent-archive.txt` 与 `worker-archive.txt`。每行使用 archive viewer 原始条目，不做子串过滤。
12. 生成 `build/phase12-task11/evidence/third-party-license-map.json`，固定 schema `phase12_distribution_evidence_v1`。每个实际发行物必须记录 `artifact`、`name`、`version`、`module_roots`、SPDX `license`、`license_file`、`license_sha256`、`source_url`；未知发行物或缺字段立即 BLOCKED。外层 launcher 条目由 Task 11-4 两遍构建补齐。
13. 生成 `payload/licenses/BUILD_ENVIRONMENT.json`：两个 Python EXE SHA-256、版本、两份 `pip freeze --all` 规范化文本及 SHA-256、PyInstaller/Pydantic 版本、三个 spec SHA-256、FFmpeg/ffprobe SHA-256。内容禁止时间戳、绝对路径和机器名，使用与 payload manifest 相同的规范 JSON。Task 11 只宣称内容寻址和构建可追溯，不宣称跨机器字节级可复现。

- [ ] **Step 5: 更新第三方许可证清单**

原位区分两条分发线：

- 正式客户安装包：继续受 `LICENSE_CONFIRMED.txt` 门禁，状态 `NOT_BUILT`。
- Task 11 测试 EXE：不是许可证豁免，只允许打包自动扫描证明存在且分发依据已核清的最小组件；缺证据即 `BLOCKED_BY_DISTRIBUTION_EVIDENCE`。

- [ ] **Step 6: 运行合同测试并提交**

```powershell
& $Python310Exe -m pytest -q `
  tests/test_phase12_task11_packaging_contract.py `
  tests/test_phase12_task11_distribution_scan.py `
  tests/test_phase12_ai_edit_packaging_contract.py
```

期望：新测试全 PASS，既有正式打包合同不回退。

```powershell
git add -- `
  local_agent_phase12_test.spec `
  ai_edit_worker_phase12_test.spec `
  requirements-phase12-test-worker.txt `
  scripts/build_phase12_test_payload.ps1 `
  docs/ai/13_ai_edit/TEST_BUILD_NOTICE_TEMPLATE.md `
  docs/ai/13_ai_edit/THIRD_PARTY_NOTICES.md `
  tests/test_phase12_task11_packaging_contract.py `
  tests/test_phase12_task11_distribution_scan.py
git diff --cached --check
git commit -m "构建：增加 Task 11 许可安全双运行时载荷"
```

## 7. Task 11-4：组合单入口 onefile 与最终两文件交付目录

**Files:**
- Create: `scripts/generate_phase12_test_payload.py`
- Create: `phase12_test_launcher.spec`
- Create: `scripts/build_phase12_single_test_exe.ps1`
- Modify: `tests/test_phase12_task11_packaging_contract.py`
- Modify: `tests/test_phase12_task11_distribution_scan.py`

- [ ] **Step 1: 为载荷生成器写红灯**

测试固定：稳定排序、相对 POSIX 路径、文件大小、流式 SHA-256、重复路径拒绝、符号链接/重解析点拒绝、秘密文件名拒绝、同提交不同 payload 得到不同指纹/版本、实际版本/提交写入测试说明。

- [ ] **Step 2: 实现载荷生成器**

命令：

```powershell
& $Python310Exe scripts/generate_phase12_test_payload.py `
  --payload-root build/phase12-task11/payload `
  --git-commit (git rev-parse HEAD) `
  --notice-template docs/ai/13_ai_edit/TEST_BUILD_NOTICE_TEMPLATE.md
```

输出：

```text
payload/payload_manifest.json
payload/TEST_BUILD_NOTICE.md
```

生成器先计算 fingerprint preimage：

```python
preimage = {
    "schema_version": "phase12_payload_fingerprint_v1",
    "notice_template_sha256": sha256(template_raw_bytes).hexdigest(),
    "files": sorted(
        ({"path": posix_relative_path, "size": size, "sha256": sha256_hex}
         for each file except payload_manifest.json and TEST_BUILD_NOTICE.md),
        key=lambda item: item["path"],
    ),
}
canonical = json.dumps(
    preimage,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
payload_fingerprint = hashlib.sha256(canonical).hexdigest()[:16]
```

`canonical` 无 BOM、无尾换行，路径 Unicode 使用 UTF-8 原文，不做 `\u` 转义或 Unicode normalization。版本固定为 `phase12-task11-<git前12位>-<payload_fingerprint>`。

必须加入含中文路径的 golden vector：schema 如上，template SHA-256 为 64 个 `d`，files 依次为 `licenses/BUILD_ENVIRONMENT.json`(size=2, hash=64 个 `c`)、`local-agent/小高AI微信助手.exe`(size=3, hash=64 个 `a`)、`worker/ai_edit_worker.exe`(size=4, hash=64 个 `b`)；完整 SHA-256 必须等于：

```text
a2b6a1da6a06499360a5738c12da0399ebae775381af5eaeb2328e753b9c28b2
```

notice 模板固定 UTF-8 无 BOM、LF 换行；生成器只做固定 token 替换，输出 UTF-8 无 BOM、LF、恰好一个尾换行。manifest 把生成后的 notice 纳入 `files` 并记录其 hash；manifest 自身不自引用。生成器不得读取环境令牌，不得把绝对路径写入产物。

- [ ] **Step 3: 新建外层 onefile spec**

入口为 `app/phase12_test_launcher.py`，名称固定 `小高AI系统测试版`，`console=False`，只把已经生成的 `payload/` 作为 datas 收入。不得从源码目录、`dist/local-agent` 或用户目录动态 collect。

- [ ] **Step 4: 实现总构建脚本**

总脚本必须：

1. 要求当前目录是 `phase12-task11` 独立 worktree，且 tracked/untracked 均 clean；验证最终批准回传的 `ApprovedTask11Commit` 是当前 HEAD 祖先。主工作区脏文件不参与判断也不作为输入。
2. 固定 `build/phase12-task11/` 与 `dist/phase12-task11-delivery/`，清理前做绝对路径前缀校验。
3. 调用 Task 11-3 payload 构建脚本，参数含 D0 批准的精确 API/frontend URL。
4. 第一次构建外层候选 EXE，只用于获取 `evidence/launcher-archive.txt`；按实际 archive 补齐 `third-party-license-map.json` 与许可证文本，任一未知发行物立即 BLOCKED。完成映射后把该 JSON 复制到 `payload/licenses/THIRD_PARTY_COMPONENTS.json`。
5. 运行载荷生成器，依据包含最终许可证映射的 payload 闭集计算指纹与版本，再运行语义化静态扫描。
6. 第二次构建最终外层 onefile；重新生成 launcher archive 并断言组件集合与第一遍许可证映射完全一致。两遍不一致即 `BLOCKED_BY_BUILD_OR_SMOKE`。
7. 最终目录只复制 `小高AI系统测试版.exe`。
8. 用 `Get-FileHash -Algorithm SHA256` 生成 `小高AI系统测试版.exe.sha256.txt`，格式固定 `<hash>  小高AI系统测试版.exe`。
9. 枚举最终目录，非精确两文件即失败并删除本次 delivery 目录。

- [ ] **Step 5: 提交构建编排**

```powershell
& $Python310Exe -m pytest -q `
  tests/test_phase12_task11_launcher.py `
  tests/test_phase12_task11_launcher_contract.py `
  tests/test_phase12_task11_packaging_contract.py `
  tests/test_phase12_task11_distribution_scan.py

git add -- `
  scripts/generate_phase12_test_payload.py `
  phase12_test_launcher.spec `
  scripts/build_phase12_single_test_exe.ps1 `
  tests/test_phase12_task11_packaging_contract.py `
  tests/test_phase12_task11_distribution_scan.py
git diff --cached --check
git commit -m "构建：增加 Task 11 单入口测试 EXE 编排"
```

## 8. Task 11-5：真实本机构建、离线 smoke、扫描与收口

**Files:**
- Modify: `docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md`
- Modify: `docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`
- Modify: `docs/ai/05_PROJECT_CONTEXT.md`
- Modify: `docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md`

- [ ] **Step 1: 从干净隔离目录执行真实 PyInstaller 构建**

只允许显式参数；不得传商户令牌和生产 URL：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_phase12_single_test_exe.ps1 `
  -Python310Exe 'C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe' `
  -Python311Exe 'C:\Users\A\miniconda3\envs\zws\python.exe' `
  -FfmpegDir $ApprovedFfmpegDir `
  -ApprovedTestApiBaseUrl $ApprovedTestApiBaseUrl `
  -ApprovedTestFrontendOrigin $ApprovedTestFrontendOrigin
```

- [ ] **Step 2: 执行真实打包 Worker 合成媒体 smoke**

使用随包 FFmpeg 的 `lavfi color` + `sine` 生成 3 秒合成 MP4，构造合法 manifest，直接启动打包后的 Worker 子进程。断言：

- exit code 0；
- `result.json` 为 succeeded；
- 720P 与 1080P 产物存在、非空；
- ffprobe 时长大于 0、分辨率匹配、有音频；
- 原合成输入 SHA-256 不变；
- 不使用客户素材、不调用网络。

- [ ] **Step 3: 执行内部 Local Agent 离线只读 smoke 与外层 verify-only**

1. 直接从 payload 启动内部 Local Agent，使用进程内随机 token、空 9000 地址、精确回环 CORS；只验证 `/health`、`/agent/version` 和携带 token 的 `/agent/ai-edit/status`，不得调用素材导入、任务创建或 Worker。
2. 调用最终 EXE `--verify-only`，只校验并释放 payload 后退出；断言未监听端口、未启动 Local Agent/Worker、未访问网络。
3. 第二次 `--verify-only` 复用闭集完整的同版本目录。
4. 在测试副本预置额外 DLL、额外目录、junction 或篡改文件，分别返回稳定完整性错误且不覆盖。

- [ ] **Step 4: 执行最终 EXE 非生产真实端到端验收**

这是 Task 11 唯一允许的产品网络窗口，只能访问 runtime profile 精确登记的非生产 frontend/API：

网络证据使用 Windows Filtering Platform 审计，子类别 GUID 固定 `{0CCE9226-69AE-11D9-BED3-505054503030}`（Filtering Platform Connection），避免系统语言差异。执行前记录 Security 日志起始 RecordId 与原 auditpol 状态；经管理员批准后仅在本测试窗口启用 success audit，并在 `finally` 恢复原状态。若无法读取/设置 Security 审计则 `BLOCKED_BY_BUILD_OR_SMOKE`，不得用应用日志替代。

浏览器必须是 Playwright 启动的全新临时 profile Chromium，禁扩展并加 `--disable-background-networking`；`context.route` 只允许批准的 frontend/API host 与 127.0.0.1，其它请求立即 abort 并记录。不得复用用户默认浏览器进程。

1. 使用专用测试账号登录非生产前端；人工在启动器掩码框输入同一商户的短期 token，不把 token 放入命令行、脚本、截图或日志。
2. 启动器先请求 `/ai-edit/agent-context`，确认 9000 返回的 merchant_id 与登录商户一致，再启动 19000。
3. 浏览器→非生产 9000 获取 token→19000 鉴权→导入合成媒体→9000 素材可见→创建任务→真实 Worker/FFmpeg→9000 终态回写，全链路通过。
4. 依次验证取消、重试新 attempt、重启恢复与旧 attempt 拒绝；不使用客户素材。
5. 验证 19000 CORS 只接受 runtime profile 的 frontend origin；其它 origin 拒绝。
6. 记录实际访问主机与次数；除两个批准主机和 127.0.0.1 外必须为 0。生产、宝塔、9100 真实模型、Milvus 和抖音发布调用为 0。

结束后读取起始 RecordId 之后的 Security Event 5156 XML，以稳定 EventData 字段提取 `Application/DestAddress/DestPort/ProcessID`。只纳入本次 launcher、释放后的 Local Agent、Worker、FFmpeg 与隔离 Chromium 进程树；批准 host 在测试开始前解析到固定 IP 集，允许目标仅该 IP 集和 loopback。保存 `evidence/wfp_connections.json`、Playwright request log 及各自 SHA-256。至少必须观察到一次非生产 API 连接；任一其它目标、审计空白或进程归因失败即阻断。

- [ ] **Step 5: 执行真实 Job Object 异常退出探针**

启动一个无关哨兵进程，再通过最终 EXE 发起足够长的合成媒体任务。确认 Worker 活跃后，使用已持有的外层进程句柄强制结束外层启动器，断言：

- Local Agent 与 Worker/FFmpeg 整棵 Job 子树在限定时间内退出；
- 无关哨兵仍存活；
- 不调用 `taskkill /PID` 数字兜底；
- 重启后 19000 端口可用，恢复逻辑按既有合同处理任务。

- [ ] **Step 6: 执行最终分发扫描与许可证映射复核**

必须同时检查 payload 目录和 PyInstaller archive 列表：

```powershell
& 'C:\Users\A\miniconda3\envs\demo_auto_wechat\Scripts\pyi-archive_viewer.exe' -l `
  'dist\phase12-task11-delivery\小高AI系统测试版.exe'
```

使用 Task 11-1 冻结的语义规则，断言实际 payload、三份 archive 列表和发行物清单无禁用组件、权重、`.env`、token、`LICENSE_CONFIRMED.txt`；spec `excludes` 与测试常量中的禁用名称不计为命中。FFmpeg buildconf 无 `--enable-nonfree`，`-L`、GPL 文本、构建来源和源码获取说明一致。

交付报告必须附三份 archive 清单 SHA-256，并逐项汇总 `third-party-license-map.json` 的组件名、版本、SPDX、许可证文件 SHA-256 和来源；映射必须覆盖 archive 中全部第三方发行物，不能只做禁入扫描。

- [ ] **Step 7: 执行可复核 Windows Defender 扫描**

运行并保存到不提交的 `build/phase12-task11/evidence/defender_status.json`：

```powershell
$ErrorActionPreference = 'Stop'
$scanStartedUtc = [DateTime]::UtcNow
$mp = Get-MpComputerStatus
if (-not $mp.AMServiceEnabled -or -not $mp.AntivirusEnabled -or -not $mp.RealTimeProtectionEnabled) { throw 'DEFENDER_UNAVAILABLE' }
if ([DateTime]$mp.AntivirusSignatureLastUpdated -lt $scanStartedUtc.AddHours(-72)) { throw 'DEFENDER_SIGNATURE_STALE' }
$before = @(Get-MpThreatDetection)
Start-MpScan -ScanType CustomScan -ScanPath (Resolve-Path 'build\phase12-task11\payload')
Start-MpScan -ScanType CustomScan -ScanPath (Resolve-Path 'dist\phase12-task11-delivery\小高AI系统测试版.exe')
$after = @(Get-MpThreatDetection)
$beforeKeys = @($before | ForEach-Object { "$($_.ThreatID)|$($_.InitialDetectionTime)|$($_.Resources -join ',')" })
$newThreats = @($after | Where-Object { "$($_.ThreatID)|$($_.InitialDetectionTime)|$($_.Resources -join ',')" -notin $beforeKeys })
if ($newThreats.Count -ne 0) { throw 'DEFENDER_THREAT_DETECTED' }
$evidence = [ordered]@{
  scan_started_utc = $scanStartedUtc.ToString('o')
  scan_finished_utc = [DateTime]::UtcNow.ToString('o')
  product_version = $mp.AMProductVersion
  engine_version = $mp.AMEngineVersion
  signature_version = $mp.AntivirusSignatureVersion
  signature_updated = $mp.AntivirusSignatureLastUpdated
  realtime_enabled = $mp.RealTimeProtectionEnabled
  scanned = @('payload', '小高AI系统测试版.exe')
  new_threats = @($newThreats)
}
$evidence | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 'build\phase12-task11\evidence\defender_status.json'
```

`Start-MpScan` 两次调用均须在 `$ErrorActionPreference='Stop'` 下正常返回后才视为各自扫描完成；任一异常立即阻断，不允许后台发起后马上取结果。证据固定记录 `AMProductVersion`、`AMEngineVersion`、`AntivirusSignatureVersion`、`AntivirusSignatureLastUpdated`、扫描开始/结束 UTC、两个扫描对象、两次命令完成状态及 before/after 差集中的 threat ID/resource。签名更新时间距扫描开始不得超过 72 小时；Defender 不可用、实时防护关闭、签名超时、命令失败或任一对象出现新增威胁时状态为 `BLOCKED_BY_DISTRIBUTION_EVIDENCE`。

- [ ] **Step 8: 执行回归矩阵**

```powershell
& $Python310Exe -m pytest -q `
  tests/test_phase12_task11_launcher.py `
  tests/test_phase12_task11_launcher_contract.py `
  tests/test_phase12_task11_packaging_contract.py `
  tests/test_phase12_task11_distribution_scan.py `
  tests/test_phase12_ai_edit_worker_contract.py `
  tests/test_phase12_ai_edit_pipeline.py `
  tests/test_phase12_ai_edit_api.py `
  tests/test_phase12_local_ai_edit_supervisor.py `
  tests/test_phase12_local_ai_edit_routes.py `
  tests/test_local_agent_auth.py `
  tests/test_p0_4a_exe_crash_fix.py `
  tests/test_p0_4a_local_agent.py
```

不得用全仓 collection 替代上述精确矩阵。失败必须区分新增回归与既有失败并给出隔离证据。

- [ ] **Step 9: 原位更新文档和最终报告**

允许状态只有：

```text
BUILT_PENDING_APPROVAL
BLOCKED_BY_DISTRIBUTION_EVIDENCE
BLOCKED_BY_BUILD_OR_SMOKE
```

报告必须回传：提交链、最终 EXE SHA-256、内容指纹版本、内部载荷闭集及逐项 SHA-256、三份 archive 清单 SHA-256、Python 逐组件许可证映射、FFmpeg `-L/-version/-buildconf` 与全部 `--enable-lib*` 组件映射、语义禁入扫描、真实 PyInstaller/Worker/FFmpeg/Job Object smoke、批准非生产主机调用与所有禁止主机 0 调用、Defender 版本/时间/结果、最终两文件枚举、token 撤销负责人/截止时间、已知能力限制和未签名 SmartScreen 风险。

- [ ] **Step 10: 提交文档收口并硬暂停**

```powershell
git add -- `
  docs/ai/13_ai_edit/PHASE12_TASK11_TEST_EXE_DELIVERY_REPORT.md `
  docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md `
  docs/ai/05_PROJECT_CONTEXT.md `
  docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md
git diff --cached --check
git commit -m "文档：收口 Task 11 单入口测试 EXE 验证"
```

## 9. 检查点 D2：Task 11 四方总验收

当前窗口必须完成四方审查：

### Spec Reviewer

- 最终交付精确两文件。
- 用户只启动一个 EXE。
- 内部双业务运行时、双业务子进程未合并；外层控制进程被如实计入进程模型。
- 真实合成媒体 720P/1080P 和取消/恢复边界有证据。
- 未把缺失 AI 能力伪造成可用。

### Code Quality Reviewer

- 载荷校验单一事实源。
- 版本目录原子释放且不自动覆盖/清理。
- 进程句柄与退出清理闭合。
- 构建环境、输入和产物内容寻址且可追溯，不虚假宣称跨机器字节级可复现；不污染 Git 和旧 dist。
- 测试不是仅搜索注释或伪造 subprocess。

### Security Reviewer

- 鉴权保持开启。
- token 不入包、不落盘、不进日志和命令行。
- Worker 子进程环境不含 Local Agent token、9000 地址、数据库 URL 或 internal token。
- 非生产 API 精确允许、无 30x、token→merchant 权威绑定、CORS 精确来源均通过；生产域名、宝塔、真实模型、生产数据库调用为 0。
- 路径穿越、符号链接/junction/其它重解析点、额外文件、端口占用、未知进程误杀探针通过。
- Windows Job Object kill-on-close 探针通过，外层异常退出不遗留 Local Agent/Worker。
- 19000 仅回环监听。

### Distribution Reviewer

- 测试包不是许可证豁免。
- 禁用模型/权重/OCR 重依赖扫描为 0 命中。
- FFmpeg 无 nonfree，实际构建对应的 GPL 文本、`-L/-version/-buildconf`、构建来源和源码获取说明齐全。
- FFmpeg buildconf 的全部 `--enable-lib*` 外部组件与 `FFMPEG_COMPONENTS.json` 精确对应，未知组件为 0。
- 实际 payload 中每个第三方组件均有可分发依据。
- 外层 Python/Tcl/Tk/PyInstaller 与内部 Python Web 运行依赖均已按实际 archive 清单覆盖，不能只审 FFmpeg。
- 最终 EXE Defender 扫描和 SHA-256 通过。

四方全 PASS 后，当前窗口原位更新 6 份权威文档并提交，才可把状态从 `BUILT_PENDING_APPROVAL` 改为：

```text
APPROVED_FOR_CUSTOMER_TEST_DELIVERY
```

即使 D2 PASS，以下状态仍保持：

```text
正式客户安装包：NOT_BUILT
Phase 13：NOT_STARTED
宝塔生产验证：NOT_STARTED，Phase 13 完成后统一执行
Phase 12 唯一 concern：baota_ai_edit_production_not_verified
```

## 10. 执行窗口首批启动指令

执行窗口收到本计划后，只执行：

```text
Task 11-0：基线、环境与分发证据预检
Task 11-1：冻结单入口、安全和分发合同红灯
```

执行要求：

1. 使用 `executing-plans`。
2. 每个 Task 独立中文提交。
3. 只显式 `git add -- <白名单文件>`。
4. 回传红灯测试精确失败、提交哈希、文件列表、网络调用数和分发证据状态。
5. Task 11-1 后硬暂停，等待当前窗口检查点 D0 审批。
