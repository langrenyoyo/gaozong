# P0-1 局域网访问排查与修复报告

**日期**：2026-06-10
**执行人**：AI

---

## 1. 当前主局域网 IP

| 项目 | 值 |
|------|-----|
| 主局域网 IP | `192.168.110.113` |
| 子网掩码 | `255.255.255.0` |
| 网关 | `192.168.110.1` |
| DNS 后缀 | `.lan` |
| 主机名 | `DESKTOP-T0HA3GO` |

排除的虚拟网卡：
- `172.19.96.1`（WSL）
- `192.168.40.1`（虚拟网络）
- `192.168.11.1`（虚拟网络）

---

## 2. auto_wechat 监听地址

| 项目 | 值 |
|------|-----|
| 绑定地址 | `0.0.0.0:9000` ✅ |
| 启动命令 | `uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload` |
| 局域网可访问 | ✅ `curl http://192.168.110.113:9000/` 返回正常 |

---

## 3. React 监听地址

| 项目 | 值 |
|------|-----|
| 绑定地址 | `0.0.0.0:5173` ✅ |
| 启动命令 | `npm run dev:lan`（即 `vite --mode lan --host 0.0.0.0 --port 5173`） |
| 局域网可访问 | ✅ `curl http://192.168.110.113:5173/` 返回正常 |

---

## 4. React API baseURL

| 模式 | 命令 | 环境文件 | API 地址 |
|------|------|----------|----------|
| 本机开发 | `npm run dev` | `.env.development` | `http://127.0.0.1:9000` |
| **局域网** | `npm run dev:lan` | `.env.lan` | `http://192.168.110.113:9000` |

**修复前**：React 以默认模式启动，API 地址为 `127.0.0.1:9000`，局域网其他机器访问时 API 请求指向访问者自己的机器。

**修复后**：使用 `npm run dev:lan`，API 地址为 `192.168.110.113:9000`，局域网其他机器可正确调用 API。

---

## 5. CORS 配置结果

**修复前**：只有 `127.0.0.1:5173`, `localhost:5173`, `192.168.110.113:5173`

**修复后**：新增 `DESKTOP-T0HA3GO:5173`（主机名访问场景）

| Origin | 状态 |
|--------|------|
| `http://127.0.0.1:5173` | ✅ |
| `http://localhost:5173` | ✅ |
| `http://192.168.110.113:5173` | ✅ |
| `http://DESKTOP-T0HA3GO:5173` | ✅ |

---

## 6. 防火墙规则结果

| 端口 | 现有规则 | 说明 |
|------|----------|------|
| TCP 9000 | ❌ 无明确规则 | 但本机通过局域网 IP 可访问 |
| TCP 5173 | ❌ 无明确规则 | 但 `192.168.110.13` 已有活跃连接 |

防火墙三个配置文件均为**开启**状态（Domain/Private/Public），但局域网访问 5173 已有成功连接记录。

**建议**：在管理员 PowerShell 中添加明确入站规则：
```powershell
netsh advfirewall firewall add rule name="auto_wechat_9000" dir=in action=allow protocol=TCP localport=9000
netsh advfirewall firewall add rule name="react_5173" dir=in action=allow protocol=TCP localport=5173
```

如果局域网仍无法访问，临时测试可关闭防火墙：
```powershell
netsh advfirewall set allprofiles state off
# 测试完成后务必恢复
netsh advfirewall set allprofiles state on
```

---

## 7. 局域网其他机器访问结果

### 已验证（本机通过局域网 IP 模拟）

| 端点 | 结果 |
|------|------|
| `http://192.168.110.113:9000/` | ✅ 返回 JSON |
| `http://192.168.110.113:9000/staff` | ✅ 4 条记录 |
| `http://192.168.110.113:9000/automation/status` | ✅ 状态正常 |
| `http://192.168.110.113:5173/` | ✅ 返回 HTML |
| `http://192.168.110.113:5173/src/api/client.ts` | ✅ baseURL=192.168.110.113:9000 |

### 已确认的外部连接

netstat 显示 `192.168.110.13:50178` → `192.168.110.113:5173` 已 ESTABLISHED，确认局域网其他机器可访问 React。

### 需在局域网机器上验证

1. 打开浏览器访问 `http://192.168.110.113:5173`
2. 按 F12 打开开发者工具 → Network 标签
3. 刷新页面，确认 API 请求指向 `http://192.168.110.113:9000/...`
4. 确认**不能**出现 `http://127.0.0.1:9000/...`

---

## 8. 修复动作汇总

| # | 问题 | 修复动作 | 文件 |
|---|------|----------|------|
| 1 | React 局域网 API 地址指向 127.0.0.1 | 新增 `dev:lan` 脚本 + 重启为 `npm run dev:lan` | `react/package.json` |
| 2 | CORS 不包含主机名 | 新增 `DESKTOP-T0HA3GO:5173` | `auto_wechat/app/main.py` |
| 3 | __pycache__ 导致 CORS 不更新 | 清除 pycache 后重启 uvicorn | （运行时修复） |

---

## 10. 最终结论

### ✅ 局域网其他机器可以访问 React 和 auto_wechat

**前提条件**：

1. React 以局域网模式启动：`npm run dev:lan`（不能用 `npm run dev`）
2. auto_wechat 以 `--host 0.0.0.0` 启动：`uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload`
3. 防火墙允许 9000 和 5173 入站（建议添加明确规则）
4. 访问者与开发机在同一网段（192.168.110.0/24）

**局域网机器访问地址**：
- React 前端：`http://192.168.110.113:5173`
- auto_wechat API 文档：`http://192.168.110.113:9000/docs`
- auto_wechat 状态：`http://192.168.110.113:9000/automation/status`
