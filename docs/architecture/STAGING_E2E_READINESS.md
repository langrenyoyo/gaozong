# Staging E2E Readiness（跨模块共享开放项）

> M03 + M01 均因 staging 环境阻断。环境恢复时共用同一套准备，不各模块重复。

## 准备清单

1. PostgreSQL 可用（auto_wechat + xg_douyin_ai_cs 两库）
2. 9000/9100 对应 commit 部署
3. 测试 Merchant（真实商户上下文）
4. 测试 Douyin Account（已授权企业号）
5. 测试 Agent（绑定到测试企业号）
6. 测试 Customer（有 DB 档案：车型/预算/城市/联系方式）
7. Webhook 公网/平台回调可达（GMP 可触发）
8. DOUYIN_AUTO_REPLY_ENABLED=true
9. AI_AUTO_REPLY_OUTBOX_ENABLED=true
10. REAL_SEND_ENABLED=true（或 dry-run 模式标注）
11. 账号级 send_enabled=true
12. GMP 凭证（DY_GMP_SECRET_KEY / DY_MAIN_ACCOUNT_ID）
13. 日志访问权限
14. 数据库观察权限

## 涉及模块 Gate

- M03：GATE-M03-01（Agent Binding→Auto Reply）/ GATE-M03-02（Auto Reply 事实）/ GATE-M03-03（Training 隔离）
- M01：GATE-01~08（8 个真实 webhook/send Gate）

## 补验证流程

环境恢复 → 共用准备 → 逐 Gate 验证 → 合格证据回填各模块 ACCEPTANCE → 升级 Baseline
