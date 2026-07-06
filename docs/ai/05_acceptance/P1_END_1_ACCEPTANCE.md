# P1-END-1 验收文档

## 阶段名称

P1 自动检测单次闭环演示版冻结

## 验收日期

2026-06-13

## 核心链路

```text
React 创建测试线索/任务
    → 9000 主系统创建 notify_sales wechat_task
    → React 将 notify_sales task_id 传给 19000 Local Agent
    → 19000 按 task_id 执行指定 notify_sales（paste_only）
    → sent=false，禁止自动发送
    → 9000 回写 pasted
    → 9000 自动绑定/创建 ReplyCheck
    → 9000 自动创建 detect_reply task
    → React 展示当前 detect_reply task
    → React 点击"执行当前检测任务 #xxx"
    → 19000 poll-and-detect 按 task_id 执行指定 detect_reply（read_only）
    → 只读微信消息，不粘贴、不发送、不按 Enter
    → 检测到 friend 侧回复"收到，已添加微信"
    → 9000 回写 checks=replied
    → 9000 回写 lead_notifications=replied
    → React 页面展示销售已回复
```

## 已验收功能

| # | 功能 | 状态 |
|---|------|------|
| 1 | notify_sales 指定 task_id 执行（P1-AUTO-1D-FIX2） | ✅ 真机通过 |
| 2 | paste_only 粘贴通知到 Aw3 | ✅ 真机通过 |
| 3 | notify_sales pasted 后自动创建 detect_reply task（P1-AUTO-1AB-FIX2） | ✅ 真机通过 |
| 4 | detect_reply 指定 task_id 执行（P1-AUTO-1D-FIX3） | ✅ 真机通过 |
| 5 | read_only 只读检测（不粘贴、不发送、不按 Enter） | ✅ 真机通过 |
| 6 | 销售回复识别（self/friend 区分 + 关键词匹配） | ✅ 真机通过 |
| 7 | checks 回写 replied | ✅ 真机通过 |
| 8 | notifications 回写 replied（send_status=销售已回复） | ✅ 真机通过 |
| 9 | React 自动回复检测面板展示 | ✅ 真机通过 |
| 10 | search-debug 安全序列化（不再 500 RecursionError） | ✅ 测试通过 |
| 11 | poll-and-execute 与 poll-and-detect 共享运行锁 | ✅ 测试通过 |

## 真机验收样例

```text
lead #71 → staff #4（Aw3）
notify_sales task #53：pasted=true，sent=false
detect_reply：detected_status=检测到有效回复，matched_reply=收到，已添加微信
notification #34：send_status=销售已回复，send_mode=wechat_task，sent_at=null
消息读取：messages_read=5
  self：[P0-FE-MAIN-2A 测试] paste_only 任务，lead #71 → staff #4
  friend：收到，已添加微信
安全结果：raw_result.pasted=true，raw_result.sent=false
          action.sent=false，action.pasted=false
          contact_verified=true，contact_verified_strategy=ocr_top_title
```

## 安全确认

| # | 安全约束 | 状态 |
|---|----------|------|
| 1 | 不自动发送（sent 必须为 false） | ✅ 确认 |
| 2 | 不按 Enter | ✅ 确认 |
| 3 | 不写输入框（detect_reply 只读） | ✅ 确认 |
| 4 | 发送链路只 paste_only | ✅ 确认 |
| 5 | 旧调度器默认禁用 | ✅ 确认 |
| 6 | 9000 不直接操作微信 | ✅ 确认 |
| 7 | target_nickname 只允许 Aw3 | ✅ 确认 |
| 8 | poll-and-detect 不调用 input_writer | ✅ 确认 |
| 9 | detect_reply action.sent=false, action.pasted=false | ✅ 确认 |
| 10 | 运行锁防止并发操作微信 | ✅ 确认 |
| 11 | 紧急停止机制生效 | ✅ 确认 |
| 12 | OCR 验证失败 → blocked | ✅ 确认 |
| 13 | contact_not_verified → 不继续 | ✅ 确认 |

## 测试结果

| 测试套件 | 结果 |
|----------|------|
| test_p0_main_5b_poll_and_execute.py | 37 passed |
| test_p1_auto_1c_poll_and_detect.py | 23 passed |
| test_p1_auto_1d_fix4_safe_json.py | 20 passed |
| **合计** | **80 passed, 0 failed** |

## 非阻塞问题

| # | 问题 | 影响 | 备注 |
|---|------|------|------|
| 1 | React "已粘贴" 展示字段可能取错 | UI 展示问题，不影响业务链路 | 后续单独修复 |
| 2 | test_p0_4a_exe_crash_fix.py 1 个旧失败 | 测试签名变更未同步 | 与 P1 无关 |
| 3 | test_p0_4a_local_agent.py 1 个旧失败 | 19000 端口占用导致 | 环境问题 |
| 4 | npm run lint 14 errors + 7 warnings | 旧代码风格问题 | 非 P1 阻塞项 |
| 5 | 8081 dev test-leads 接口中文可能乱码 | Content-Type charset | 非 P1 主链路 |
| 6 | 旧 pending 队列中可能有历史任务 | 已通过 task_id 机制绕过 | 后续做清理策略 |

## 已完成修复清单

| 修复 | 内容 |
|------|------|
| P1-AUTO-1A/B | detect_reply task 支持 + 检测结果回写 + detected_status / detect_count |
| P1-AUTO-1AB-FIX2 | notify_sales pasted 后自动创建 detect_reply task + ReplyCheck 绑定 |
| P1-AUTO-1C | 19000 新增 /agent/tasks/poll-and-detect + read_only + 回写 |
| P1-AUTO-1C-UTF8 | 19000 响应 charset=utf-8 修复 PowerShell 中文乱码 |
| P1-AUTO-1D-FIX2 | poll-and-execute 支持 task_id 指定执行 |
| P1-AUTO-1D-FIX3 | poll-and-detect 支持 task_id 指定执行 |
| P1-AUTO-1D-FIX4 | search-debug/search-result-debug 安全序列化防止 500 |

## 当前版本定位

- ✅ 自动检测单次闭环演示版
- ❌ 不是后台无限自动轮询版
- ❌ 不是自动发送版
- ❌ 不是多客户生产版
- ❌ 不是完整产品化版

## 下一阶段建议

| 优先级 | 建议 | 说明 |
|--------|------|------|
| P1-END-2 | 修复前端 pasted 展示字段 | UI 取错字段 |
| P1-END-3 | 清理/归档旧 pending 任务策略 | 避免 UI 混淆 |
| P2-A | 后台定时轮询检测 | 从手动触发升级为自动 |
| P2-B | 客户配置化关键词/工作时间/销售 | 多销售多配置 |
| P2-C | 多客户隔离 | 多个 Windows Agent |
| P2-D | 报表与超时策略 | 完善监控 |
