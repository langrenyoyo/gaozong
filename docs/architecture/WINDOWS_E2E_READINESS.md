# Windows E2E Readiness（跨模块共享开放项）

> M04 因 Windows 19000 未运行阻断。环境恢复时共用准备，不各模块重复。

## 准备清单

1. Windows 测试机可用
2. 小高AI微信助手.exe（对应 commit 版本）
3. 19000 监听正常（127.0.0.1:19000）
4. server_url 指向正确 9000
5. 合法 Local Agent token + merchant 映射
6. 微信客户端版本 + 已登录
7. 测试联系人
8. 允许发送测试消息
9. 日志目录可访问
10. 截图/OCR 依赖
11. 9000 可观察日志
12. 测试 Lead/Staff/Task fixture

## 涉及模块 Gate

- M04: W01-W06（6 个 Windows Gate）

## 补验证流程

Windows 恢复 → 共用准备 → 逐 W-Gate 验证 → 合格证据回填 M04 ACCEPTANCE → 升级 Baseline
