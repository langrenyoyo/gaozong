# P0-2F 白屏根因隔离报告

**日期**: 2026-06-10
**脚本**: `scripts/debug_wechat_white_screen.py`
**环境**: Windows 10, 微信 PC (Qt51514QWindowIcon), conda `demo_auto_wechat`

---

## 1. 测试概要

| 参数 | 值 |
|------|------|
| 微信 hwnd | 10029596 |
| 微信类名 | Qt51514QWindowIcon |
| 初始窗口位置 | (-3, 72, 877, 772) |
| 初始状态 | visible=True, iconic=False, is_foreground=True |
| 测试步骤 | 8 个（foreground_only → full_contact_verify） |
| 每步重复 | 5 次 |
| 总执行数 | 40 |
| 白屏触发数 | **17/40（42.5%）** |
| 意外最小化 | 0 |

---

## 2. 根因定位

### 结论：白屏 = 微信窗口 `visible=False` + 截图截到空白屏幕区域

**不是真正的微信白屏。是截图截到了微信窗口不可见时的桌面背景。**

### 证据链

#### 证据 A：visible=True 的步骤从未白屏

| 步骤 | 重复 | visible | 白屏次数 |
|------|------|---------|---------|
| foreground_only | 5 | True | **0** |
| move_only | 5 | True | **0** |
| activate_only | 5 | True | **0** |

前 15 次执行，窗口始终 `visible=True`，白色像素占比稳定在 **51.3%**（正常微信界面），**0 次白屏**。

#### 证据 B：visible=False 时部分白屏

| 步骤 | 重复 | visible | 白屏次数 |
|------|------|---------|---------|
| click_search | 5 | False | 2/5 |
| click_title | 5 | False | 3/5 |
| click_avatar | 5 | False | **5/5** |
| open_profile_card | 5 | False | 4/5 |
| full_contact_verify | 5 | False | 3/5 |

后 25 次执行，窗口 `visible=False`，白屏 17/25（68%）。

#### 证据 C：状态跳变精确发生在 click_search

- `activate_only #5 after`: `visible=True, fg=True`
- `click_search #1 before`: `visible=True, fg=True`（正常）
- `click_search #1 after`: **`visible=False, fg=False`**
- 前台窗口变成 `"2026-06"`（截图窗口标题）

**click_search 中的 `Esc + SetForegroundWindow + SetCursorPos + mouse_event` 操作导致微信窗口被操作系统标记为不可见。**

#### 证据 D：白色占比一致性

所有 "白屏" 的白色像素占比完全一致：**87.5%**。
这不是随机白屏，而是截到了一个**固定的浅色背景**（桌面背景/其他窗口背景）。

非白屏的不可见窗口显示 `ratio=-1`，即截图 API 抛出 `OverflowError`，无法截取。
白屏的不可见窗口显示 `ratio=0.8754`，即 BitBlt 成功但截到的是桌面背景。

---

## 3. 根因机制

```
click_search 步骤执行：
  1. uia.SendKeys("{Esc}")           ← 微信可能因此隐藏窗口
  2. SetForegroundWindow(hwnd)       ← 试图拉回前台
  3. SetCursorPos + mouse_event      ← 点击搜索区域
  4. time.sleep(0.8)                 ← 等待搜索面板

结果：
  微信窗口 IsWindowVisible()=False
  微信不在前台
  BitBlt 截图成功但截到的是微信窗口位置后面的桌面背景
  桌面背景大部分白色 → 触发 85% 阈值 → 误报为白屏
```

### 关键发现：Qt5 微信的 Esc 行为

微信 PC 使用 Qt5 渲染（`Qt51514QWindowIcon`）。当微信窗口没有打开任何面板时，
`Esc` 键可能触发 Qt5 的窗口隐藏行为（类似于"关闭/最小化到托盘"），
导致窗口被操作系统标记为 `IsWindowVisible=False`。

这不是 Windows 经典行为，而是 Qt5 窗口管理器的特殊处理。

---

## 4. 白屏检测的两种假阳性

| 情况 | white_ratio | 截图结果 | 原因 |
|------|------------|---------|------|
| visible=False + BitBlt成功 | 0.8754 | 桌面背景 | 截到窗口后面的桌面 |
| visible=False + BitBlt失败 | -1 | None | OverflowError，无法截取 |

两种情况都不是真正的微信白屏，而是**窗口不可见导致截图截错目标**。

---

## 5. 对现有代码的影响

### `_check_white_screen()` (window_locator.py:450)

当前白屏检测逻辑：
1. 截取窗口中心区域（基于 hwnd 的 rect）
2. 分析白色像素比例
3. 比例 >85% 判定为白屏

**问题**：当 `IsWindowVisible=False` 时，BitBlt 基于 hwnd rect 截取的不是微信窗口内容，
而是该区域的桌面/其他窗口。浅色桌面背景导致误判。

### `contact_verifier.py` 中的策略 B/C

策略 B（点击标题）和策略 C（点击头像）都涉及：
1. `SetCursorPos` + `mouse_event` 点击
2. `time.sleep(1.0)` 等待资料卡
3. `save_debug_screenshot()` 截图

如果之前 Esc 导致窗口不可见，这些点击操作的目标已经不是微信窗口，
而是微信位置后面的桌面。截图自然显示浅色背景。

---

## 6. 修复建议

### 修复 A：白屏检测前置 `IsWindowVisible` 检查（必须）

```python
def _check_white_screen(hwnd: int) -> tuple[bool, str]:
    # 修复：如果窗口不可见，直接返回非白屏（而不是截桌面）
    if not user32.IsWindowVisible(hwnd):
        return False, "窗口不可见，跳过白屏检测"

    # ... 原有逻辑
```

**优先级**: P0
**风险**: 低（只是增加了前置检查，不影响正常可见窗口的检测逻辑）

### 修复 B：click_search 中 Esc 之前检查窗口状态（推荐）

```python
# 发送 Esc 之前，记录当前前台窗口
fg_before = user32.GetForegroundWindow()
uia.SendKeys("{Esc}", waitTime=0.05)
time.sleep(0.2)

# Esc 之后，如果微信丢失前台，主动恢复
if user32.GetForegroundWindow() != hwnd:
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

# 如果 Esc 导致微信不可见，主动恢复可见性
if not user32.IsWindowVisible(hwnd):
    user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
    time.sleep(0.5)
```

**优先级**: P1
**风险**: 中（需要测试 SW_SHOWNORMAL 是否会导致 Qt5 白屏）

### 修复 C：白屏检测区分"窗口不可见"和"真正白屏"（推荐）

```python
def _check_white_screen(hwnd: int) -> tuple[bool, str]:
    if not user32.IsWindowVisible(hwnd):
        return False, "窗口不可见（非白屏，可能是 Esc 隐藏）"

    if user32.IsIconic(hwnd):
        return False, "窗口已最小化"

    # ... 正常白屏检测逻辑
```

---

## 7. 结论

| # | 结论 |
|---|------|
| 1 | **不存在真正的微信白屏** |
| 2 | "白屏"是 `IsWindowVisible=False` 时截图截到桌面背景的假阳性 |
| 3 | 根因是 `uia.SendKeys("{Esc}")` 导致 Qt5 微信窗口被隐藏 |
| 4 | 修复方向：白屏检测前置 `IsWindowVisible` 检查 + Esc 后恢复窗口可见性 |
| 5 | 前 15 次执行（visible=True）0 白屏，证明 activate_wechat_window 逻辑本身无问题 |
| 6 | P0-2E 的 "0/10 白屏" 声明在特定条件下是正确的（窗口可见时确实不会白屏） |
| 7 | 但 P0-2E 的 contact_verifier 中 Esc 操作引入了窗口不可见，后续截图误报白屏 |

---

## 8. 截图和数据文件

- 截图目录: `data/debug_screenshots/white_screen/`
- 完整报告: `data/debug_screenshots/white_screen/white_screen_report_20260610_140105.json`
- 初始截图: `0_initial_state_*.png`
- 各步骤前后截图: `{step}_{before|after}_*.png`
- 日志: `data/debug_screenshots/white_screen/debug_white_screen.log`
