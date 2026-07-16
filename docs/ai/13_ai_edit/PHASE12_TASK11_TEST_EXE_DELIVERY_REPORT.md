# Phase 12 Task 11 单入口测试 EXE 交付报告

> **状态：** `BUILT_FOR_CUSTOMER_TEST`
> **交付物：** `小高AI系统测试版.exe`（仅此一个文件）
> **执行窗口：** 基于 `b4779ae`（解除 Task 11 开发与构建门禁），使用 executing-plans 直接完成 Task 11-1~11-3，不设中间检查点、许可证审查、构建审批或发送审批。

## 1. 最终交付

| 项 | 值 |
|---|---|
| EXE 路径 | `dist/phase12-task11/小高AI系统测试版.exe` |
| 大小 | 248,983,506 字节（约 237 MB） |
| SHA-256 | `20C7918B49B46C1173875888C33B673E750C9F5F42D3263CD468CE2CBC8C821C` |
| 构建脚本 | `scripts/build_phase12_single_test_exe.ps1` |
| 双 Python | Local Agent = Python 3.10（`demo_auto_wechat`），Worker = Python 3.11（`zws`） |
| 随包 FFmpeg | Gyan 8.1.1-full_build（ffmpeg.exe / ffprobe.exe） |
| 烘焙配置 | `phase12_test_config.json`（test_api_url=`https://merchant.xiaogaoai.cn/api` / frontend_url=`https://merchant.xiaogaoai.cn/` / merchant_id=`m_nc_2bba00063cc13016`，运行时不依赖环境变量，已从 EXE CArchive 提取验证） |

## 2. 运行安全边界（计划 §2，全部保留）

1. **token 运行时输入**：tkinter 掩码框读取，只进内存 `LOCAL_AGENT_TOKEN`，不进源码 / Git / 日志 / argv / EXE。
2. **19000 回环鉴权**：启动器强制 `LOCAL_AGENT_AUTH_REQUIRED=true`，只监听 `127.0.0.1:19000`；运行时单 token 通过烘焙商户 ID 绑定，不依赖开发机 `LOCAL_AGENT_TOKENS`。
3. **浏览器边界**：仅把烘焙前端 URL 的精确 origin 加入 CORS 白名单，并允许浏览器 Private Network Access 预检；不使用通配来源。
4. **Worker 凭据隔离**：`app/local_agent_main._build_worker_env()` 剥离 token、商户绑定、鉴权开关、数据库地址与 internal token，Worker 子进程不继承 Local Agent 控制面凭据。
5. **本轮未启动**：宝塔、生产数据库、真实付费模型、抖音发布。

## 3. 真实验证结果（Task 11-3）

### 3.1 测试 EXE 启动 + /health
- 启动随包 `local_agent_phase12_test.exe`（注入 token + AUTH_REQUIRED=true）。
- `GET /health` → **200**，`{"success":true,"service":"auto_wechat_local_agent","host":"127.0.0.1","port":19000,...}`。
- `OPTIONS /health` 与 `OPTIONS /runtime/status`（Origin=`https://merchant.xiaogaoai.cn` + Private Network Access）均为 **200**，返回精确 `Access-Control-Allow-Origin` 与 `Access-Control-Allow-Private-Network: true`。
- App 创建、uvicorn 启动均为 1 次；心跳按单线程周期执行，不再成对上报。

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
入口回归：20 passed
Local Agent / Task 11 相关回归：64 passed
```
覆盖：`test_p0_4a_exe_crash_fix`、`test_phase12_task11_launcher`、`test_local_agent_runtime`、`test_local_agent_auth`、`test_phase7_fix2_local_agent_auth`、`test_phase12_local_ai_edit_routes`、`test_local_agent_heartbeat`；均无新增失败。

## 4. 本轮根因修复清单

| 文件 | 问题 | 修复 |
|---|---|---|
| `apps/ai_edit/worker_main.py` | 无 `if __name__ == "__main__"` 块，PyInstaller EXE 收集后不调用 `main()`，静默 rc=0 退出 | 末尾补 `if __name__ == "__main__": raise SystemExit(main())` |
| `app/local_agent_main.py` | ai_edit 注册块用 `Path` 但块内无导入 → 打包后 `name 'Path' is not defined`，9 路由静默未注册 | 块内补 `from pathlib import Path` |
| `local_agent_phase12_test.spec` | excludes 含 `numpy`，但 `wechat_ui/contact_searcher.py` 顶层 `import numpy` → EXE 启动即 `ModuleNotFoundError` 崩溃 | 从 excludes 移除 `numpy`，注释说明不可排除原因 |
| `scripts/build_phase12_single_test_exe.ps1` | UTF-8 no-BOM 在 PS 5.1 被读为 GBK → 中文字面量解析错误 | 改 UTF-8 BOM；`Ensure-PyInstaller` 用 `import` 检查替代 `-m`（避免 PS 5.1 把 native stderr 当终止错误） |
| `app/phase12_test_launcher.py` | 新建：标准库单入口启动器（tkinter 掩码 token、端口占用只读探测不杀进程、Job Object 进程树清理） | — |
| `app/local_agent_main.py` | 公网 HTTPS 前端访问回环地址时 CORS/PNA 预检返回 400 | 从烘焙前端 URL 提取精确 origin，并启用 Private Network Access 预检 |
| `app/phase12_test_launcher.py` / `app/auth/local_agent_auth.py` | 干净电脑没有开发环境 `LOCAL_AGENT_TOKENS`，19000 无法把运行时 token 绑定到商户 | 启动器注入商户 ID 与强制鉴权；鉴权层支持单 token + 单商户绑定，token 不重复存储 |
| `app/local_agent_exe_entry.py` | 启动信息和 uvicorn 各创建一次 App，产生双心跳线程与重复 Supervisor | 只创建一次 App，同一实例用于路由打印和 uvicorn |

## 5. 当前缺失能力（一期边界，未在 Task 11 范围）

- 真实 ASR / 视觉分析未接入：Worker `_analyze` 返回空转写，`_plan` 仅 keep 主素材区间；增稳 `stabilize_enabled=False`。一期 AI 剪辑 smoke 只验证 ffmpeg 渲染链（720P/1080P 合成 + 音频），不验证智能剪辑决策。
- 测试 API / 前端 URL 已为真实值（`https://merchant.xiaogaoai.cn/api` / `https://merchant.xiaogaoai.cn/`，商户 `m_nc_2bba00063cc13016`），烘焙进 EXE 经 CArchive 提取确认。
- 不含安装器、自动更新、卸载器、系统服务（计划 §2 明确不新增）。
- 旧包已在干净虚拟机暴露 CORS/PNA、错误 API 基址和商户 token 绑定问题；当前新包已在开发机以打包后内部 EXE 完成预检、鉴权三态、9 路由与单 App 启动验证，仍需重新复制到干净虚拟机做最终零安装复测。
- **未进入 Phase 13、未做宝塔生产验证**（本轮硬约束）。

## 6. 结论

`BUILT_FOR_CUSTOMER_TEST` —— `小高AI系统测试版.exe` 已用带 `/api` 的真实测试 API、前端地址与商户 ID 重建；CArchive 配置提取、`/health`、公网前端 CORS/PNA 预检、19000 鉴权三态、9 路由、单 App 初始化与端口释放均通过。token 不入包，干净电脑不再依赖开发环境 token 映射，Worker 凭据隔离保持生效；新包仍需在干净虚拟机复测。
