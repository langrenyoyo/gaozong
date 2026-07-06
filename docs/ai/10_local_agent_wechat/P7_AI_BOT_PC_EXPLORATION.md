# ai-bot-pc 架构与微信自动化能力探索报告

> 探索日期：2026-06-09
> 软件版本：1.0.4
> 探索方式：合法灰盒（目录结构、配置文件、日志、数据库、明文源码）

---

## 1. 软件基本信息

| 项目 | 内容 |
|------|------|
| 安装路径 | `C:\Users\A\AppData\Local\Programs\ai-bot-pc` |
| 主程序 | `qm-ai-bot.exe`（201 MB） |
| 软件名称 | `ai-bot-pc`（AI员工中台） |
| 版本 | 1.0.4 |
| 技术栈 | **Electron 38.1.2** + **Vue 3** + **TypeScript** |
| 构建工具 | electron-vite |
| 代码保护 | **V8 字节码编译**（`.jsc` 文件，不可读） |
| 更新服务 | Aliyun OSS（`q-ai-bot.oss-cn-shenzhen.aliyuncs.com`） |
| 界面模式 | **远程嵌入**（不使用 Electron renderer 本地界面） |

### 技术栈判断依据

| 依据 | 发现 |
|------|------|
| Electron | `LICENSE.electron.txt`、`v8_context_snapshot.bin`、`snapshot_blob.bin` |
| Vue 3 | renderer JS 开头 `@vue/shared v3.5.21` |
| TypeScript | eslint 配置引用 `@electron-toolkit/eslint-config-ts` |
| electron-vite | `package.json` 中 `homepage: "https://electron-vite.org"` |
| V8 字节码 | `out/main/bytecode-loader.cjs` + `.jsc` 文件 |
| 远程 UI | `.kiro/steering/pc.md` 明确说明「通过远程嵌入方式加载 ai-bot-ui 提供的 UI」 |

---

## 2. 目录结构摘要

```
C:\Users\A\AppData\Local\Programs\ai-bot-pc\
├── qm-ai-bot.exe              ← Electron 主程序（201 MB）
├── resources\
│   ├── app.asar               ← 打包的应用资源（20 MB）
│   ├── app-update.yml         ← 自动更新配置
│   └── elevate.exe            ← 权限提升工具
├── locales\                   ← Chromium 语言包
├── *.dll                      ← Chromium 依赖（d3dcompiler, ffmpeg, libEGL 等）
├── *.pak                      ← Chromium 资源包
├── LICENSE.electron.txt       ← Electron 许可证
└── LICENSES.chromium.html     ← Chromium 许可证

app.asar 内部结构：
├── package.json               ← 包名 ai-bot-pc, version 1.0.4
├── .kiro/steering/pc.md       ← ★ 项目指导文档（可读）
├── docs/升级测试流程.md         ← 自动更新测试流程
├── eslint.config.mjs          ← ESLint 配置
├── resources\
│   ├── asar-version.json      ← { version: "1.0.0", buildTime: "2026-04-06" }
│   ├── icon.ico
│   └── icon.png
├── out\
│   ├── main\
│   │   ├── index.js           ← 入口：加载 bytecode-loader → index.jsc
│   │   ├── bytecode-loader.cjs← ★ V8 字节码加载器（可读）
│   │   └── index.jsc          ← 主进程逻辑（142 KB，不可读）
│   ├── preload\
│   │   ├── index.js           ← 入口：加载 index.jsc
│   │   ├── index.jsc          ← 预加载逻辑（1.7 KB，不可读）
│   │   ├── webview.js         ← 入口：加载 webview.jsc
│   │   ├── webview.jsc        ← WebView 逻辑（2.8 KB，不可读）
│   │   └── chunks\
│   │       └── index-ByF8EnXb.jsc
│   └── renderer\
│       ├── index.html         ← 最小 HTML 壳
│       └── assets\
│           └── index-DyYkDd_E.js ← Vue 3 + 最小化壳（171 KB）
└── node_modules\              ← 第三方依赖
    ├── axios, ali-oss, dayjs, lodash, md5
    ├── winston, winston-daily-rotate-file
    ├── adm-zip, async, xml2js
    └── electron-updater

用户数据目录：C:\Users\A\AppData\Roaming\ai-bot-pc\
├── localConfig.json           ← { serialno: "00:15:5d:1d:b2:ef" }（MAC 地址）
├── logs\
│   └── app_20260609.log       ← 当日日志
├── Preferences                ← Electron 偏好
├── Network\                   ← Cookie、Session Storage
└── GPUCache\, DawnGraphiteCache\ 等 ← Chromium 缓存
```

---

## 3. 可读/不可读边界

### 可读文件

| 文件 | 内容 |
|------|------|
| `package.json` | 包名、版本、依赖列表 |
| `app-update.yml` | 更新服务器地址 |
| `.kiro/steering/pc.md` | 项目架构说明 |
| `docs/升级测试流程.md` | Mac 增量更新测试流程 |
| `eslint.config.mjs` | TypeScript + Vue lint 配置 |
| `out/main/bytecode-loader.cjs` | V8 字节码加载器源码 |
| `out/renderer/index.html` | 最小 HTML 壳 |
| `resources/asar-version.json` | 版本号 |
| `logs/*.log` | 运行日志（winston-daily-rotate） |
| `localConfig.json` | 序列号（MAC 地址） |

### 不可读文件

| 文件 | 原因 |
|------|------|
| `out/main/index.jsc` | V8 字节码（142 KB），包含所有主进程逻辑 |
| `out/preload/index.jsc` | V8 字节码（1.7 KB），预加载逻辑 |
| `out/preload/webview.jsc` | V8 字节码（2.8 KB），WebView 逻辑 |
| `out/renderer/assets/index-*.js` | 生产构建压缩 JS（仅 Vue 3 运行时壳） |

**结论**：所有业务逻辑都在 `.jsc` 字节码中，无法在不反编译的情况下阅读。`.jsc` 不是 JS 源码，是 V8 编译后的字节码。

---

## 4. 微信相关能力发现

### 总体结论

**ai-bot-pc 桌面客户端本身不包含任何微信自动化能力。**

### 详细分析

#### 是否有微信窗口定位

❌ **否。** node_modules 中没有 `uiautomation`、`robotjs`、`puppeteer`、`node-window-manager` 等窗口操作库。日志中没有出现任何微信窗口相关的记录。

#### 是否有联系人搜索

❌ **否。** 没有相关依赖或日志痕迹。

#### 是否有消息发送

❌ **否。** 没有发现 `pyperclip`、`clipboardy`（Node 剪贴板库）、`iohook`、`nut.js` 等输入模拟库。

#### 是否有消息监听

❌ **否。** 没有发现消息轮询、WebSocket 消息监听等机制。

#### 是否使用 UIAutomation

❌ **否。** 没有 `uiautomation`、`@nicegram/robot`、`windows-automation` 等 Node 库。

#### 是否使用剪贴板

❌ **否。** 没有 `electron-clipboard-extended`、`clipboardy` 等剪贴板库。

#### 是否使用协议/注入

❌ **否。** 没有 DLL 注入、协议逆向相关库。`resources/elevate.exe` 是用于权限提升（UAC）的标准工具。

### 界面远程加载机制

`.kiro/steering/pc.md` 明确说明：

> 重要：**不使用 Electron 的 renderer 层来实现界面**，而是通过远程嵌入方式加载 `ai-bot-ui` 提供的 UI

这意味着 ai-bot-pc 是一个**瘦客户端**，实际界面和业务逻辑运行在远程服务器上。如果服务端有微信自动化能力，那也是在服务端实现，不在桌面客户端。

---

## 5. 任务分发能力发现

### 总体结论

**ai-bot-pc 桌面客户端不包含任务分发、销售管理、线索分配等功能。**

#### 是否有任务队列

❌ **否。** 没有 `bull`、`bee-queue`、`agenda`、`kue` 等任务队列库。

#### 是否有销售/成员/客服概念

❌ **否。** 日志和配置中没有出现相关痕迹。

#### 是否有线索分配逻辑

❌ **否。** 没有发现相关逻辑。

#### 是否有调度器

⚠️ **仅有自动更新调度。** `electron-updater` 负责版本更新检查，不是业务调度。

---

## 6. 本地 API / 端口发现

### 端口 21199

日志中反复出现：

```
杀掉端口 21199 的 HTTP 服务进程失败
Port 21199 cleaned
PROD 38.1.2 win32 x64 ... 21199
```

分析：
- **21199 是本地 HTTP 服务端口**
- 应用启动时在本地监听此端口
- 退出时尝试杀掉占用此端口的进程
- 可能用于与本地其他服务通信（如 AI 后端代理）
- 当前进程未运行，无法验证实际监听状态

### 网络请求方向

- **更新服务**：`https://q-ai-bot.oss-cn-shenzhen.aliyuncs.com/client/pc/prod/auto-updates/`
- **UI 加载**：远程加载 `ai-bot-ui`（具体 URL 在 `.jsc` 字节码中，不可读）
- **端口 21199**：本地 HTTP 服务

### renderer JS 分析

renderer `index-DyYkDd_E.js`（171 KB）仅包含 Vue 3 运行时壳：
- 只找到 `http://w`（3 次）和 `https://v`（1 次）— 可能是 Vue 内部 URL
- 没有发现 localhost、API 端点、WebSocket 地址

---

## 7. 数据库与配置文件发现

### 本地数据库

❌ **没有发现任何数据库文件。** 用户数据目录中没有 `.db`、`.sqlite`、`.sqlite3` 文件。

Electron 的 `Network/Cookies` 是 Chromium 内置的 Cookie 存储（LevelDB），不是业务数据库。

### 配置文件

| 文件 | 内容 | 业务价值 |
|------|------|----------|
| `localConfig.json` | `{"serialno":"00:15:5d:1d:b2:ef"}` | MAC 地址绑定 |
| `app-update.yml` | 更新服务器地址 | 运维配置 |
| `Preferences` | Electron 默认偏好 | 无业务价值 |
| `Local State` | Chromium 加密密钥 | 无业务价值 |
| `asar-version.json` | `{"version":"1.0.0","buildTime":"2026-04-06"}` | 资源版本 |

### node_modules 依赖

全是标准工具库，无微信/自动化/任务相关包：

| 类别 | 包名 |
|------|------|
| HTTP | axios, follow-redirects, agentkeepalive |
| OSS | ali-oss |
| 日志 | winston, winston-daily-rotate-file, logform |
| 工具 | lodash, dayjs, md5, async, adm-zip, xml2js |
| 更新 | electron-updater |
| 编码 | iconv-lite, mime-types |

---

## 8. 日志发现

### 日志文件

- `app_20260609.log` — 当日唯一日志（winston-daily-rotate，保留 14 天）

### 关键日志摘要

```
18:58:35 [INFO] PROD 38.1.2 win32 x64 ... 21199
18:58:35 [INFO] Screen width: 1920, Screen height: 1040
18:58:35 [INFO] window ready-to-show
18:58:35 [INFO] 检查到有更新，开始下载新版本
18:58:37 [INFO] 下载完毕！提示安装更新
18:59:15 [INFO] Port 21199 cleaned
18:59:15 [INFO] Auto install update on quit
19:01:11 [INFO] window ready-to-show
19:01:12 [INFO] 没有可用更新
19:01:23 [ERROR] 杀掉端口 21199 的 HTTP 服务进程失败
19:06:17 [INFO] 没有可用更新
```

### 日志分析结论

| 分析项 | 结论 |
|--------|------|
| 微信窗口 | ❌ 未出现 |
| 联系人/消息 | ❌ 未出现 |
| 任务执行 | ❌ 未出现（仅有更新任务） |
| 错误信息 | 仅有端口清理失败（进程不存在时正常报错） |
| 业务流程 | ❌ 无业务日志 |

---

## 9. 对 auto_wechat 的可借鉴点

### 总体结论

**ai-bot-pc 桌面客户端对 auto_wechat 的微信自动化需求无可直接借鉴的技术实现。**

ai-bot-pc 是一个远程 UI 壳客户端，所有微信自动化能力（如果有）在服务端实现。桌面客户端只负责：
1. 加载远程 Web 界面
2. 提供本地端口通信（21199）
3. 管理自动更新
4. 设备序列号绑定

### 可借鉴的架构思想

| 思想 | 说明 | 对 auto_wechat 的启发 |
|------|------|----------------------|
| 远程 UI + 本地服务分离 | ai-bot-pc 界面在远程，本地只做桥接 | auto_wechat 已经是这种模式（React → API → 后端） |
| 本地 HTTP 端口 | 端口 21199 可能用于本地服务间通信 | auto_wechat 使用端口 9000，已实现 |
| V8 字节码保护 | `.jsc` 编译防止源码泄露 | auto_wechat 是内部工具，不需要代码保护 |
| electron-updater 自动更新 | 增量更新（blockmap 差异下载） | auto_wechat 不需要桌面客户端更新机制 |

### 不建议借鉴点

| 不建议 | 原因 |
|--------|------|
| 尝试对接 ai-bot-pc 端口 21199 | 协议未知，且该软件可能未运行 |
| 依赖 ai-bot-pc 的远程 UI | 与 auto_wechat 的 React UI 是独立系统 |
| 参考 ai-bot-pc 的微信自动化实现 | 桌面客户端不包含此能力 |

---

## 10. 不建议借鉴点

| 不建议项 | 原因 |
|----------|------|
| 反编译 `.jsc` 字节码 | 违反合法探索边界 |
| 分析 ai-bot-pc 网络协议 | 服务端 API 未公开，属于私有协议 |
| 依赖 ai-bot-pc 做微信自动化 | 客户端无此能力，服务端不可控 |
| 将 ai-bot-pc 纳入 auto_wechat 架构 | 两个系统职责不同，没有集成基础 |

---

## 11. P7 实施建议

### 探索结论

ai-bot-pc 是一个**瘦客户端 Electron 壳**，远程加载 `ai-bot-ui` 服务端界面。桌面客户端不包含任何微信自动化、任务分发、线索管理能力。

**对 P7 的影响**：ai-bot-pc 不改变 P7 方案设计。auto_wechat 应继续使用自己的 `input_writer.py` + `uiautomation` 方案。

### P7 实施路线（维持不变）

| 阶段 | 内容 | 状态 |
|------|------|------|
| **P7-0** | 联系人自动定位探索 | ❌ ai-bot-pc 无可参考实现；wxauto 版本不兼容；**MVP 不做** |
| **P7-1** | 探索报告 + 窗口定位策略调整 | ✅ 已完成（含本报告） |
| **P7-2** | 新增 `lead_notifications` 模型和 Schema | 待实施 |
| **P7-3** | 通知文本生成服务 | 待实施 |
| **P7-4** | 写入当前微信窗口服务（复用 `input_writer`） | 待实施 |
| **P7-5** | React 发送线索按钮 + 状态展示 | 待实施 |
| **P7-6** | 通知记录前端展示 | 待实施 |
| **P7-7** | 后续探索自动搜索销售昵称 | 待规划 |

### P7-0 联系人自动定位 — 结论

| 探索对象 | 结果 | 可用性 |
|----------|------|--------|
| 小猫AI员工（wxauto） | 核心在 `.pyd`，且微信版本不兼容 | ❌ 不可用 |
| ai-bot-pc | 瘦客户端，无微信自动化能力 | ❌ 不可用 |
| auto_wechat 自研 | `uiautomation` 搜索微信联系人 | ⚠️ 可行但 MVP 不需要 |

**最终结论**：P7 MVP 维持方案 A（用户手动打开销售聊天窗口），不自动搜索联系人。自动搜索作为 P7-7 后续探索项。

---

## 附录：探索边界声明

本次探索严格遵循合法边界：

- ✅ 查看目录结构和文件列表
- ✅ 读取明文配置文件（JSON、YAML、MD）
- ✅ 读取运行日志
- ✅ 列出 asar 内文件结构
- ✅ 提取并阅读明文 JS 文件（package.json、bytecode-loader.cjs、index.html）
- ✅ 检查 node_modules 依赖列表
- ✅ 检查用户数据目录

- ❌ 未反编译 .jsc 字节码
- ❌ 未破解授权或绕过加密
- ❌ 未分析 DLL 或注入机制
- ❌ 未修改任何文件
- ❌ 未嗅探网络通信
