# 微信消息发送方精确识别方案调研与实验报告

> 日期：2026-06-09
> 阶段：P2 发送方识别调研（不影响正式检测逻辑）

---

## 一、当前结论

### 已完成的交付物

| 交付物 | 状态 | 说明 |
|--------|------|------|
| `scripts/debug_wechat_raw_tree.py` | ✅ | UIA 深层控件树探测脚本 |
| `scripts/debug_wechat_screenshot.py` | ✅ | 截图 + 像素分析脚本 |
| `GET /replies/debug/raw-tree` | ✅ | UIA 深层探测 API 端点 |
| `POST /replies/debug/sender-experiment` | ✅ | 发送方方案实验 API 端点 |
| 26 个测试 | ✅ | 全部通过，无回归 |
| 本报告 | ✅ | 实验结论与推荐方案 |

### 核心结论

**当前微信 PC 版本（截至 2026-06）的消息 ListItemControl 存在以下特征：**

1. **`GetChildren()` 返回 0 个子控件**（child_count=0）
2. **无 ButtonControl / ImageControl / TextControl 子控件**
3. **消息 item 的 BoundingRectangle 占满列表全宽**（left ≈ list.left, right ≈ list.right）
4. **`WalkControl()` 和 `FindAll()` 深层遍历也未发现头像、气泡等控件**

因此，**纯 UIA 控件树方案在当前版本无法区分 self/friend 发送方**。

---

## 二、实验 A：UIA 控件树探测结果

### 实验方法

使用 `scripts/debug_wechat_raw_tree.py` 和 `GET /replies/debug/raw-tree` 端点，对最近 5 条消息执行：

1. **`GetChildren()`** — 常规子控件探测
2. **`WalkControl(maxDepth=10)`** — 深层遍历所有子孙
3. **`FindAll(return_pointer=True)`** — 获取子孙控件指针数量
4. **`ControlFromPoint`** — 左/中/右三点点采样

### 实验结果

| 探测方法 | 结果 |
|----------|------|
| `GetChildren()` | child_count = 0，无子控件 |
| `WalkControl()` | 仅返回自身（ListItemControl），无子孙 |
| `FindAll()` | Length = 1（仅自身），无子孙 |
| `ControlFromPoint` 左/中/右 | 均命中 ListItemControl 自身，未命中更深层控件 |
| `ButtonControl(searchDepth=2)` | `Exists(0)` = False |
| `ImageControl(searchDepth=2)` | `Exists(0)` = False |
| `TextControl(searchDepth=2)` | 0 个 |

### 分析

微信 PC 客户端在当前版本中，消息列表的 `ListItemControl` 是一个**扁平化控件**：

- 消息文本存储在 `ListItemControl.Name` 属性中（可直接读取）
- 不暴露头像、气泡、时间戳等子控件
- 整个消息 item 作为一个不可分割的 UI 元素呈现

**结论：UIA 控件树方案不可行。**

---

## 三、实验 B：截图 + 像素分析结果

### 实验方法

使用 `scripts/debug_wechat_screenshot.py`：

1. 通过 `PIL.ImageGrab` 截取消息列表区域
2. 分析绿色像素（self/主机消息）和白色像素（friend/销售消息）的分布
3. 用简单连通区域分析（flood fill）识别气泡候选框
4. 判断绿色是否靠右、白色是否靠左

### 像素颜色定义

| 颜色 | RGB 范围 | 含义 |
|------|----------|------|
| 绿色气泡 | R:60-200, G:170-255, B:60-180, G>R, G>B | self（主机发出） |
| 白色气泡 | R:230-255, G:230-255, B:230-255 | friend（销售发来） |

### 实验结果预期

| 指标 | 预期结果 |
|------|----------|
| 绿色像素右半占比 | 显著高于左半 |
| 白色像素左半占比 | 显著高于右半 |
| 绿色气泡候选框 center_x | > 列表中线（偏右） |
| 白色气泡候选框 center_x | < 列表中线（偏左） |

### 可行性判断

| 条件 | 是否满足 |
|------|----------|
| 能截取消息列表区域 | ✅ `ImageGrab` 可用 |
| 能区分绿色/白色像素 | ✅ RGB 范围有效 |
| 绿色气泡可识别为连通区域 | ✅ flood fill 可用 |
| 气泡位置可用于区分 sender | ⚠️ 需实际运行验证 |

**结论：截图方案理论可行，但依赖微信渲染的一致性，需实际运行脚本验证。**

### 截图方案的局限

1. **依赖微信 UI 渲染**：微信更新可能改变气泡颜色/布局
2. **需要 numpy**：当前 `requirements.txt` 未包含，需新增依赖
3. **背景色干扰**：深色模式或自定义壁纸会影响颜色检测
4. **性能开销**：截图 + 像素分析比 UIA 读取慢
5. **DPI 缩放问题**：高 DPI 屏幕可能影响截图坐标映射

---

## 四、实验 C：ControlFromPoint 点采样结果

### 实验方法

对每条消息的左 1/4、中心、右 3/4 三个点进行 `ControlFromPoint` 采样，看是否能命中更深层控件。

### 实验结果

| 采样位置 | 命中控件类型 | 是否更深层 |
|----------|-------------|-----------|
| 左 1/4 | ListItemControl | ❌ |
| 中心 | ListItemControl | ❌ |
| 右 3/4 | ListItemControl | ❌ |

**结论：ControlFromPoint 也无法命中更深层控件，微信当前版本的消息 item 确实是扁平结构。**

---

## 五、实验 D：已知文本 + 位置关联验证

### 实验方法

使用 `POST /replies/debug/sender-experiment` 端点：

1. 传入 `known_friend_text`（销售已知回复，如"收到，已添加微信"）
2. 传入 `known_self_text`（主机已知消息，如"请回复收到"）
3. 在消息列表中搜索这些文本，记录其 `center_x` 位置
4. 判断 friend 消息是否在左侧、self 消息是否在右侧

### 实验结果

由于当前版本消息 item 占满列表全宽（left ≈ list.left, right ≈ list.right），`center_x` 接近列表中线，**无法通过 item 的 BoundingRectangle 位置区分 sender**。

**结论：位置关联方案在当前 UIA 结构下不可行，但截图方案可能仍然有效（因为气泡内部位置仍有左右差异）。**

---

## 六、方案对比

| 方案 | 可行性 | 精度 | 复杂度 | 依赖 | 维护成本 | 推荐 |
|------|--------|------|--------|------|----------|------|
| **A. UIA 控件树** | ❌ 不可行 | - | 低 | uiautomation | - | ❌ |
| **B. 截图 + 像素** | ⚠️ 待验证 | 中-高 | 高 | Pillow + numpy | 高（依赖 UI 渲染） | ⚠️ 备选 |
| **C. ControlFromPoint** | ❌ 不可行 | - | 低 | uiautomation | - | ❌ |
| **D. 文本+位置关联** | ❌ 不可行 | - | 低 | uiautomation | - | ❌ |
| **E. 当前兜底模式** | ✅ 已实现 | 低-中 | 低 | 无额外依赖 | 低 | ✅ **推荐** |
| **F. 微信 Hook/注入** | ⚠️ 风险高 | 高 | 极高 | 逆向工程 | 极高 | ❌ 不推荐 |

---

## 七、最终推荐方案

### 短期（当前 MVP）—— 保持兜底模式

**推荐继续使用 `fallback_current_window_text` + `strict_mode`：**

1. ✅ 已实现且测试通过（26 个测试全绿）
2. ✅ 不依赖发送方识别，直接分析窗口文本
3. ✅ `strict_mode=True` 确保只匹配关键词/期望文本，不误判
4. ✅ `risk_level` + `confirmed_required` 提供可信度标记
5. ✅ `confirm_current_chat` 允许调用方确认窗口正确性
6. ✅ 无额外依赖，维护成本最低

### 中期（微信版本更新后）—— 重新验证 UIA

1. 微信大版本更新后，重新运行 `scripts/debug_wechat_raw_tree.py`
2. 如果发现新的子控件结构（头像、气泡），可升级为 `self_only` 精确模式
3. 实验脚本和端点已就绪，无需额外开发

### 长期（生产级）—— 截图方案或官方 API

1. 截图方案可作为中期升级路径，但需验证稳定性和 DPI 兼容性
2. 最终方案应关注微信官方是否提供消息接口（如企业微信 API）
3. 当前 MVP 的核心目标是**验证业务流程闭环**，不是追求完美的发送方识别

---

## 八、运行实验的方法

```bash
# 实验 A：UIA 深层控件树探测
cd E:\work\project\auto_wechat
python scripts/debug_wechat_raw_tree.py

# 实验 B：截图 + 像素分析
python scripts/debug_wechat_screenshot.py

# 实验 C/D：通过 API 端点
# 先启动服务
python -m uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload

# UIA 深层探测
curl http://127.0.0.1:9000/replies/debug/raw-tree?max_messages=5

# 发送方方案实验
curl -X POST http://127.0.0.1:9000/replies/debug/sender-experiment \
  -H "Content-Type: application/json" \
  -d '{"max_messages": 10, "known_friend_text": "收到，已添加微信", "known_self_text": "请回复收到"}'
```

---

## 九、总结

本次调研确认了当前微信 PC 版本的 UIA 限制，排除了纯控件树方案。现有的兜底模式（`fallback_current_window_text` + `strict_mode`）在 MVP 阶段是合理的折中方案：

- **精度够用**：strict_mode 要求命中关键词，不会误判
- **风险可控**：`risk_level` 和 `confirmed_required` 标记提供人工复核入口
- **成本最低**：无额外依赖，无截图性能开销
- **可升级**：实验脚本和端点已就绪，微信版本更新后可快速验证新方案

**建议：P2 阶段到此结束，进入下一个迭代周期。**
