# Phase 12 Task 11 单入口测试 EXE 交付报告

> **状态：** `BUILT_FOR_CUSTOMER_TEST`
> **交付物：** `小高AI系统测试版.exe`（仅此一个文件）
> **执行窗口：** 基于 `b4779ae`（解除 Task 11 开发与构建门禁），使用 executing-plans 直接完成 Task 11-1~11-3，不设中间检查点、许可证审查、构建审批或发送审批。

## 1. 最终交付

| 项 | 值 |
|---|---|
| EXE 路径 | `dist/phase12-task11/小高AI系统测试版.exe` |
| 大小 | 248,602,640 字节（约 237 MB） |
| SHA-256 | `707701B8145055FFD4EF385EBCA95497311B98C17A04D2ED583386FB092C2D40` |
| 构建脚本 | `scripts/build_phase12_single_test_exe.ps1` |
| 双 Python | Local Agent = Python 3.10（`demo_auto_wechat`），Worker = Python 3.11（`zws`） |
| 随包 FFmpeg | Gyan 8.1.1-full_build（ffmpeg.exe / ffprobe.exe） |
| 烘焙配置 | `phase12_test_config.json`（test_api_url / frontend_url / merchant_id，运行时不依赖环境变量） |

## 2. 运行安全边界（计划 §2，全部保留）

1. **token 运行时输入**：tkinter 掩码框读取，只进内存 `LOCAL_AGENT_TOKEN`，不进源码 / Git / 日志 / argv / EXE。
2. **19000 回环鉴权**：`LOCAL_AGENT_AUTH_REQUIRED=true`，只监听 `127.0.0.1:19000`，`X-Local-Agent-Token` 鉴权保持开启。
3. **Worker 凭据隔离**：`app/local_agent_main._build_worker_env()` 剥离 `*_TOKEN` / `*INTERNAL_TOKEN*` / `NEWCAR_*` / `*DATABASE_URL*`，Worker 子进程不继承 Local Agent token、数据库地址、internal token。
4. **本轮未启动**：宝塔、生产数据库、真实付费模型、抖音发布。

## 3. 真实验证结果（Task 11-3）

### 3.1 测试 EXE 启动 + /health
- 启动随包 `local_agent_phase12_test.exe`（注入 token + AUTH_REQUIRED=true）。
- `GET /health` → **200**，`{"success":true,"service":"auto_wechat_local_agent","host":"127.0.0.1","port":19000,...}`。

### 3.2 19000 鉴权开启（受保护路由 `GET /agent/ai-edit/materials`）
| 请求 | 状态码 | 结论 |
|---|---|---|
| 无 token | 401 `LOCAL_AGENT_TOKEN_MISSING` | 鉴权开启 ✅ |
| 错误 token | 401 `LOCAL_AGENT_TOKEN_INVALID` | 鉴权开启 ✅ |
| 正确 token | 200 | 通过鉴权 ✅ |

> 注：测试前发现并清理了一个 07-13 残留的正式版 Local Agent 进程占用 19000，确认本次探活命中随包测试 EXE 本身。

### 3.3 ai-edit 路由注册
- 9 个 `/agent/ai-edit/*` 路由全部注册成功（materials / jobs / status / cancel / retry 等）。
- **根因修复：** `app/local_agent_main.py` 的 ai_edit 注册块使用 `Path` 但块内缺少 `from pathlib import Path`，导致打包后 `name 'Path' is not defined`，路由注册被 `try/except` 静默吞掉。补局部导入后修复。该缺陷为预先存在（单元测试直接调 `create_ai_edit_router` 绕过），首次真实 EXE 启动暴露。

### 3.4 真实 Worker + FFmpeg smoke
- 随包 ffmpeg 合成 3 秒带音频视频源（testsrc 640×480 + sine 440Hz）。
- 调随包 `ai_edit_worker.exe`，注入 `AI_EDIT_FFMPEG_BINARY` / `AI_EDIT_FFPROBE_BINARY`。
- `result.json` status=`succeeded`，产物 2 个。
- ffprobe 验证：
  - 720P：`720×1280`，有音频，duration=3.0s ✅
  - 1080P：`1080×1920`，有音频，duration=3.0s ✅

### 3.5 进程树退出
- 终止测试 EXE 进程后，`127.0.0.1:19000` 监听立即释放（listen_count=0），Local Agent 进程死亡。
- 启动器通过 Windows Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000`）保证：启动器退出 / 崩溃 → OS 关闭 job 句柄 → Local Agent 及其 Worker 子进程一并终止。该机制由 `tests/test_phase12_task11_launcher.py` 覆盖（端口占用不杀未知进程、token 不泄露、Worker 环境隔离）。

### 3.6 相邻回归
```
88 passed, 37 warnings in 16.30s
```
覆盖：`test_phase12_task11_launcher` + `test_phase12_ai_edit_worker_contract` + `test_phase12_ai_edit_pipeline` + `test_phase12_local_ai_edit_supervisor` + `test_phase12_local_ai_edit_routes` + `test_local_agent_auth`。

修复 Path 导入后单独回归上述 4 套件：`53 passed`，无回归。

## 4. 本轮根因修复清单

| 文件 | 问题 | 修复 |
|---|---|---|
| `apps/ai_edit/worker_main.py` | 无 `if __name__ == "__main__"` 块，PyInstaller EXE 收集后不调用 `main()`，静默 rc=0 退出 | 末尾补 `if __name__ == "__main__": raise SystemExit(main())` |
| `app/local_agent_main.py` | ai_edit 注册块用 `Path` 但块内无导入 → 打包后 `name 'Path' is not defined`，9 路由静默未注册 | 块内补 `from pathlib import Path` |
| `local_agent_phase12_test.spec` | excludes 含 `numpy`，但 `wechat_ui/contact_searcher.py` 顶层 `import numpy` → EXE 启动即 `ModuleNotFoundError` 崩溃 | 从 excludes 移除 `numpy`，注释说明不可排除原因 |
| `scripts/build_phase12_single_test_exe.ps1` | UTF-8 no-BOM 在 PS 5.1 被读为 GBK → 中文字面量解析错误 | 改 UTF-8 BOM；`Ensure-PyInstaller` 用 `import` 检查替代 `-m`（避免 PS 5.1 把 native stderr 当终止错误） |
| `app/phase12_test_launcher.py` | 新建：标准库单入口启动器（tkinter 掩码 token、端口占用只读探测不杀进程、Job Object 进程树清理） | — |

## 5. 当前缺失能力（一期边界，未在 Task 11 范围）

- 真实 ASR / 视觉分析未接入：Worker `_analyze` 返回空转写，`_plan` 仅 keep 主素材区间；增稳 `stabilize_enabled=False`。一期 AI 剪辑 smoke 只验证 ffmpeg 渲染链（720P/1080P 合成 + 音频），不验证智能剪辑决策。
- 测试 API / 前端 URL 为占位值（`https://test-api.example.com` / `https://test.example.com`），心跳上报必然失败（预期）。
- 不含安装器、自动更新、卸载器、系统服务（计划 §2 明确不新增）。
- **未进入 Phase 13、未做宝塔生产验证**（本轮硬约束）。

## 6. 结论

`BUILT_FOR_CUSTOMER_TEST` —— `小高AI系统测试版.exe` 已完成真实 PyInstaller + Worker + FFmpeg smoke 验证，token 不入包、19000 回环鉴权保持开启、Worker 凭据隔离生效。直接回传，不等待许可证审查、构建审批或发送审批。
