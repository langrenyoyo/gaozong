# Phase 0 上下文同步执行包

> 本执行包只供独立执行窗口使用。本审批窗口只负责制定、审批和评审，不参与编码。

## 目标

同步小高AI系统一期确认后的项目上下文，消除旧文档和旧前端口径对后续开发的误导，并用合同测试防止旧约束回流。

## 阶段边界

### 本阶段必须做

1. 更新 `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md`：
   - 一期包含 AI剪辑、一键过审。
   - AI剪辑由 `auto_edit` 先独立完成，后续源码迁入 `auto_wechat` 仓库。
   - 一键过审复制改造 `douyinAPI` 现有实现，运行时不依赖 `douyinAPI`。
   - 规则字段从旧 4 项改为 5 项：线索分配、短视频/直播留资管理表、每日线索销售反馈表、线索溯源表、销售单车成本表。
   - 留资口径为 `extracted_phone`、`extracted_wechat`、`all_extracted_contacts` 任一存在。
   - 自动发送旧硬门禁全部放开，但保留违禁词替换、人工接管、限频、失败回写、幂等、紧急停止。
   - 商户管理、管理员账号、登录、功能授权仍归 NewCarProject/used-car。

2. 更新 `CLAUDE.md`：
   - 移除或覆盖“业务自动派单发送仍禁止”“AI 回复 auto_send 恒为 false”等旧口径。
   - 保留微信 UI 自动化底线：不读微信数据库、不 DLL 注入、不协议逆向、Local Agent 只监听 `127.0.0.1:19000`。
   - 明确本文档若与已确认一期计划冲突，以新计划为准。

3. 核对 `frontend/src/features/capabilities.ts`：
   - 确认 `auto_wechat:ai_edit` 已存在。
   - 确认不新增权限码。
   - 若注释或命名显示“预留码，一期不交付”，改为“AI剪辑与一键过审共用入口权限”。

4. 新增合同测试 `tests/test_xiaogao_phase1_context_contract.py`：
   - 检查文档包含新范围。
   - 检查文档不再包含旧硬门禁。
   - 检查权限码仍复用现有清单。

### 本阶段禁止做

1. 不改数据库模型。
2. 不写迁移脚本。
3. 不改发送业务逻辑。
4. 不改前端页面交互。
5. 不启动服务。
6. 不触发任何真实抖音、微信、巨量广告请求。

## 执行窗口上下文

执行窗口开始前必须阅读：

1. `CLAUDE.md`
2. `AGENTS.md`
3. `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md`
4. `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md`
5. `frontend/src/features/capabilities.ts`

## 实现子代理任务说明

请在独立执行窗口执行 Phase 0。你可以修改文件，但只能在本执行包允许范围内修改。

### 允许修改文件

- `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md`
- `CLAUDE.md`
- `frontend/src/features/capabilities.ts`
- `tests/test_xiaogao_phase1_context_contract.py`

如果你认为必须修改其他文件，先返回 `NEEDS_CONTEXT`，不要自行扩大范围。

### 建议测试内容

新增 `tests/test_xiaogao_phase1_context_contract.py`，测试意图如下：

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD_CONTEXT = ROOT / "docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md"
CLAUDE = ROOT / "CLAUDE.md"
CAPABILITIES = ROOT / "frontend/src/features/capabilities.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase1_context_includes_confirmed_scope():
    text = _read(PRD_CONTEXT)
    required = [
        "AI剪辑",
        "一键过审",
        "auto_edit",
        "douyinAPI",
        "auto_wechat:ai_edit",
        "短视频/直播留资管理表",
        "每日线索销售反馈表",
        "线索溯源表",
        "销售单车成本表",
        "all_extracted_contacts",
    ]
    missing = [item for item in required if item not in text]
    assert missing == []


def test_phase1_context_removes_obsolete_hard_gates():
    combined = _read(PRD_CONTEXT) + "\n" + _read(CLAUDE)
    obsolete = [
        "AI剪辑是独立需求",
        "不属于本项目一期交付",
        "业务自动派单发送仍禁止",
        "sent 必须为 false",
        "AI 回复 auto_send 恒为 false",
        "系统最终保持 auto_send=false",
    ]
    leaked = [item for item in obsolete if item in combined]
    assert leaked == []


def test_phase1_context_keeps_runtime_safety_boundaries():
    combined = _read(PRD_CONTEXT) + "\n" + _read(CLAUDE)
    required = [
        "违禁词",
        "人工接管",
        "限频",
        "失败回写",
        "幂等",
        "紧急停止",
        "不读取微信数据库",
        "不 DLL 注入",
        "不微信协议逆向",
        "127.0.0.1:19000",
    ]
    missing = [item for item in required if item not in combined]
    assert missing == []


def test_phase1_reuses_existing_permission_codes():
    text = _read(CAPABILITIES)
    assert 'aiEdit: "auto_wechat:ai_edit"' in text
    assert 'douyinAiCs: "auto_wechat:douyin_ai_cs"' in text
    assert 'agent: "auto_wechat:agent"' in text
    assert "auto_wechat:ai_video" not in text
    assert "auto_wechat:ad_review" not in text
```

如现有文档保留旧口径是为了描述“已推翻的旧约束”，不要让测试误判。做法是把旧约束移动到“历史废止项”并用不同措辞表达，例如“旧约束已废止：微信派单禁止真实发送”，避免仍出现 `sent 必须为 false` 这类会被后续 agent 直接复制的硬句子。

### 执行步骤

1. 创建或更新测试文件。
2. 运行：

```powershell
pytest tests/test_xiaogao_phase1_context_contract.py -v
```

预期：首次运行应失败，指出旧文档口径未同步。

3. 更新允许范围内的文档和权限说明。
4. 再次运行：

```powershell
pytest tests/test_xiaogao_phase1_context_contract.py -v
```

预期：通过。

5. 运行文档格式检查：

```powershell
git diff --check -- docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md CLAUDE.md frontend/src/features/capabilities.ts tests/test_xiaogao_phase1_context_contract.py
```

预期：无输出，退出码为 0。

6. 返回阶段结果，不在本窗口提交合并决定。

## 实现子代理回传格式

```text
阶段：Phase 0 上下文同步
状态：DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
变更文件：
数据库迁移：无
测试命令：
测试结果：
自审结论：
剩余风险：
需要本窗口审批的问题：
```

## Spec Reviewer 清单

Spec Reviewer 只检查是否符合需求，不做代码风格评审。

必须确认：

1. `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md` 不再把 AI剪辑和一键过审排除在一期之外。
2. AI剪辑描述为：同事先完成，后续源码迁入 `auto_wechat` 仓库。
3. 一键过审描述为：复制改造 `douyinAPI` 现有代码，运行时不依赖 `douyinAPI`。
4. 规则字段是 5 项，不是旧 4 项。
5. 留资口径包含 `all_extracted_contacts`。
6. 自动发送是“放开旧硬门禁”，不是“删除所有安全保护”。
7. 文档保留微信自动化底线。
8. 权限码没有新增。
9. 商户管理、管理员账号、登录、功能授权仍归上游。
10. 测试能阻止旧口径回流。

Spec Reviewer 结论格式：

```text
Spec Reviewer 结论：Approved / Changes Required
问题列表：
是否允许进入代码质量评审：是 / 否
```

## Code Quality Reviewer 清单

Code Quality Reviewer 在 Spec Approved 后执行。

必须确认：

1. Phase 0 只修改允许范围内文件。
2. 测试是合同测试，不依赖外部服务、不启动服务、不访问网络。
3. 测试断言稳定，不因为普通说明文字轻易误伤。
4. 文档表述清晰，后续 agent 不会把旧约束误认为仍有效。
5. 没有密钥、token、绝对本机敏感路径新增。
6. 没有格式问题，`git diff --check` 通过。
7. 没有把业务实现偷偷塞进 Phase 0。

Code Quality Reviewer 结论格式：

```text
Code Quality Reviewer 结论：Approved / Changes Required
问题列表：
剩余风险：
```

## 本窗口审批清单

本窗口收到执行结果后，按以下项目审批：

1. 执行窗口是否完整回传了状态、变更文件、测试命令、测试结果、两类 reviewer 结论。
2. 是否没有数据库迁移和业务代码改动。
3. 是否保留了用户已确认的 15 项需求。
4. 是否没有扩大 Phase 0 范围。
5. 是否可以允许进入 Phase 1 数据迁移骨架。

审批结论只能是：

```text
通过：允许进入 Phase 1。
有条件通过：允许准备 Phase 1，但必须在 Phase 1 前补齐指定文档/测试问题。
不通过：返回执行窗口修复后重新评审。
```
