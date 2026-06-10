# P0-2G 微信窗口隐藏与白屏误判修复报告

**日期**: 2026-06-10
**前置**: P0-2F 白屏根因隔离（已确认根因为 Esc 导致窗口隐藏 + 截桌面误判）

> **状态修正（2026-06-10）：P0-2G = 部分修复**
>
> P0-2G 修复了"窗口隐藏导致截桌面背景"的假阳性（17/40 → 0/40 白屏误判）。
> 但真实世界验证仍观察到微信窗口**可见但内容不渲染**（客户区灰色/空白）。
> 这是一个不同的问题：窗口 `IsWindowVisible=True`、未最小化，但 UI 内容未正确渲染。
>
> **P0-2G 修复范围：**
> - ✅ Esc 导致窗口隐藏
> - ✅ 截桌面背景误判为白屏
> - ✅ 白屏检测前置可见性检查
> - ✅ 搜索流程 Esc 清理
>
> **未修复（需要后续排查）：**
> - ❌ 窗口可见但内容不渲染
> - ❌ DWM 渲染状态
> - ❌ GPU 加速交互
> - ❌ 微信客户端刷新时机
> - ❌ 前台激活后等待内容渲染完成
>
> **不要标记白屏问题为"已完全解决"，直到截图验证确认内容渲染正常。**

---

## 1. 根因确认

P0-2F 已定位：
- `uia.SendKeys("{Esc}")` 导致 Qt5 微信窗口被隐藏（`IsWindowVisible=False`）
- 后续截图截到桌面浅色背景（白色占比 87.5%）
- `_check_white_screen()` 无前置可见性检查，将桌面背景误判为白屏
- **不存在真正的微信白屏**

---

## 2. 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `app/wechat_ui/window_locator.py` | 1. `_check_white_screen()` 新增 `IsWindow/IsWindowVisible/IsIconic` 前置检查 |
|  | 2. 新增 `ensure_wechat_visible()` 窗口可见性恢复函数 |
|  | 3. 修复 `import ctypes.wintypes` 覆盖闭包变量的 bug |
| `app/wechat_ui/contact_searcher.py` | 移除搜索流程中的 `uia.SendKeys("{Esc}")` |
| `app/wechat_ui/contact_verifier.py` | 1. 导入 `ensure_wechat_visible` |
|  | 2. 策略 B/C 中替换直接 Esc 为 `_close_profile_card_safe()` |
|  | 3. 新增 `_close_profile_card_safe()` 辅助函数（优先点击空白、Esc 回退+恢复） |
| `scripts/debug_wechat_white_screen.py` | 移除所有 Esc 使用，改为 `_click_blank_area()` |
| `tests/test_p0_2g.py` | 新增 13 个测试（白屏前置检查、ensure_visible、搜索无Esc、资料卡安全关闭） |
| `tests/test_p0_2e.py` | 修复 3 个旧白屏测试的 mock 方式（改用 `patch.object` 真实 ctypes） |

---

## 3. 白屏检测修复说明

`_check_white_screen()` 新增前置检查：

```python
# P0-2G 安全前置检查
if not user32.IsWindow(hwnd):
    return False, "窗口句柄无效（跳过白屏检测）"
if not user32.IsWindowVisible(hwnd):
    return False, "窗口不可见（跳过白屏检测，避免截到桌面背景）"
if user32.IsIconic(hwnd):
    return False, "窗口已最小化（跳过白屏检测）"
```

**效果**：窗口不可见/最小化时，直接返回 `is_white=False`，不再尝试截屏和像素分析。

附带修复：`import ctypes.wintypes` 改为 `import ctypes.wintypes as _wintypes`，避免 Python 编译器将 `ctypes` 误判为局部变量。

---

## 4. Esc 使用清理说明

### 已移除的 Esc

| 位置 | 原用途 | 替代方案 |
|------|--------|---------|
| `contact_searcher.py:_do_search_once` | 关闭可能残留的搜索面板 | 移除（清空搜索框已在 nickname_input 阶段用 Ctrl+A + Backspace） |

### 已替换的 Esc

| 位置 | 原用途 | 替代方案 |
|------|--------|---------|
| `contact_verifier.py` 策略 B | 关闭资料卡 | `_close_profile_card_safe()` → 优先点击空白区域 |
| `contact_verifier.py` 策略 C | 关闭资料卡 | `_close_profile_card_safe()` → 优先点击空白区域 |

### 保留的 Esc（有安全保护）

`_close_profile_card_safe()` 中 Esc 作为回退方案：
1. 优先点击聊天区域空白处关闭资料卡
2. 点击空白失败时才用 Esc
3. Esc 后立即调用 `ensure_wechat_visible()` 恢复窗口可见性
4. 记录 `esc_hid_wechat_window` 标志

---

## 5. ensure_wechat_visible 实现说明

```python
def ensure_wechat_visible(hwnd=None) -> dict:
    """确保微信窗口可见，必要时恢复"""
    # 已可见 → 直接返回 ok
    if visible and not iconic:
        return {"success": True, "recovered": False}

    # 最小化 → SW_RESTORE
    # 不可见 → SW_SHOW
    # 恢复后 → SetForegroundWindow

    # 验证恢复结果
    return {"success": recovered, "recovered": recovered}
```

特点：
- 不依赖外部模块，直接使用 `ctypes.windll.user32`
- 支持传入 hwnd 或自动查找
- 返回详细状态信息，便于调试

---

## 6. 调试脚本复测结果

运行 `scripts/debug_wechat_white_screen.py --step all --repeat 5`：

| 步骤 | 重复 | 白屏 | visible=False |
|------|------|------|---------------|
| foreground_only | 5 | **0** | 5* |
| move_only | 5 | **0** | 5* |
| activate_only | 5 | **0** | **0** |
| click_search | 5 | **0** | **0** |
| click_title | 5 | **0** | **0** |
| click_avatar | 5 | **0** | **0** |
| open_profile_card | 5 | **0** | **0** |
| full_contact_verify | 5 | **0** | **0** |

\* foreground_only 和 move_only 的 visible=False=5 是因为初始窗口不可见，这两步不做窗口恢复。activate_only 后全部恢复可见。

**修复前 vs 修复后对比：**

| 指标 | 修复前 (P0-2F) | 修复后 (P0-2G) |
|------|---------------|---------------|
| 白屏触发数 | 17/40 | **0/40** |
| visible=False (click_search+) | 25/25 | **0/25** |
| 意外最小化 | 0 | 0 |

---

## 7. 单元测试结果

```
tests/test_p0_2g.py — 13 tests PASSED
  ✅ test_not_visible_returns_false
  ✅ test_invalid_hwnd_returns_false
  ✅ test_minimized_returns_false
  ✅ test_visible_window_does_check
  ✅ test_already_visible_returns_ok
  ✅ test_hidden_window_restored
  ✅ test_minimized_window_restored
  ✅ test_restore_failure
  ✅ test_search_flow_no_esc_in_code
  ✅ test_close_card_function_exists
  ✅ test_close_card_clicks_blank_first
  ✅ test_close_card_esc_fallback_with_recovery
  ✅ test_verify_function_no_direct_esc

全量测试: 177 passed, 0 failed
```

---

## 8. 是否仍出现窗口隐藏

**否。** `activate_only` 之后的所有步骤（click_search → full_contact_verify）均 `visible=True`，窗口不再被 Esc 隐藏。

---

## 9. 是否仍出现白屏误判

**否。** 40 次执行中白屏触发 0 次。即使窗口初始不可见（foreground_only/move_only），白屏检测也会正确跳过而非误判。

---

## 10. 是否可以继续 P0-2H 联系人确认/发送复测

⚠️ **有条件继续。**

P0-2G 修复了窗口隐藏和假阳性白屏误判（17/40 → 0/40），但真实世界验证仍观察到窗口可见但内容不渲染的情况。

继续联系人确认/发送复测的前提：
- 微信窗口在自动化流程中保持可见（P0-2G 已确保）
- 白屏检测不再误判桌面背景（P0-2G 已确保）
- Esc 不再导致窗口隐藏（P0-2G 已确保）
- 177 个单元测试全部通过

**风险提示：**
- 窗口可见但内容不渲染的问题仍存在
- 未来自动化操作前应增加截图验证，确认内容已渲染
- 不要标记白屏问题为"已完全解决"
- 后续需排查：DWM 渲染状态、GPU 加速交互、微信客户端刷新时机、前台激活后等待内容渲染
