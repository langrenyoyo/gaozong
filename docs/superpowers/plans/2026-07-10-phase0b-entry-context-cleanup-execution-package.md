# Phase 0-B 入口上下文残留清理执行包

> 本执行包只供独立执行窗口使用。本审批窗口只负责制定、审批和评审，不参与编码。

## 目标

清理 Phase 0 后仍残留在入口上下文中的旧自动发送硬门禁口径，避免后续执行窗口读取 `AGENTS.md` 或 `docs/ai/05_PROJECT_CONTEXT.md` 后按旧约束开发。

## 阶段边界

### 本阶段必须做

1. 更新 `AGENTS.md`：
   - 保留项目入口、语言规范、NewCarProject 边界、微信自动化底线。
   - 把旧的抖音 AI 回复“不实发”口径改为：一期后续按 AI 托管和后端 gate 放开真实发送。
   - 把旧的微信派单“不实发”口径改为：一期后续按联系人验证、前台焦点、违禁词、限频、失败回写、幂等、紧急停止 gate 接入真实发送。
   - 明确 Phase 0-B 只是上下文同步，不代表业务发送代码已经完成。

2. 更新 `docs/ai/05_PROJECT_CONTEXT.md`：
   - 同步 AI剪辑、一键过审进入一期范围。
   - 同步 `auto_edit` 后续迁入本仓库、`douyinAPI` 仅复制改造且运行时不依赖。
   - 同步 5 个微信助手规则字段。
   - 同步留资口径包含 `all_extracted_contacts`。
   - 清理入口上下文中的旧自动发送硬门禁表述。

3. 更新或新增入口上下文合同测试：
   - 可扩展 `tests/test_xiaogao_phase1_context_contract.py`。
   - 也可新增 `tests/test_xiaogao_phase0b_entry_context_contract.py`。
   - 测试必须覆盖 `AGENTS.md` 和 `docs/ai/05_PROJECT_CONTEXT.md`。

### 本阶段禁止做

1. 不改数据库模型。
2. 不写迁移脚本。
3. 不改发送业务逻辑。
4. 不改前端页面交互。
5. 不改 `input_writer`、`contact_searcher` 或任何微信 UI 自动化代码。
6. 不启动服务。
7. 不触发任何真实抖音、微信、巨量广告请求。
8. 不清理历史验收文档中的历史事实记录。
9. 不处理前端页面旧文案，前端旧文案留到 Phase 13。

## 执行窗口上下文

执行窗口开始前必须阅读：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/ai/05_PROJECT_CONTEXT.md`
4. `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md`
5. `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md`
6. `docs/superpowers/plans/2026-07-10-phase0-context-sync-execution-package.md`

执行窗口应基于 Phase 0 已完成的工作区继续执行，推荐工作区：

```text
E:\work\project\auto_wechat\.worktrees\phase0-context-sync
```

## 实现子代理任务说明

请在独立执行窗口执行 Phase 0-B。你可以修改文件，但只能在本执行包允许范围内修改。

### 允许修改文件

- `AGENTS.md`
- `docs/ai/05_PROJECT_CONTEXT.md`
- `tests/test_xiaogao_phase1_context_contract.py`
- `tests/test_xiaogao_phase0b_entry_context_contract.py`

如果你认为必须修改其他文件，先返回 `NEEDS_CONTEXT`，不要自行扩大范围。

### 建议测试内容

优先新增 `tests/test_xiaogao_phase0b_entry_context_contract.py`，避免把 Phase 0 的测试变得过宽。测试意图如下：

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
PROJECT_CONTEXT = ROOT / "docs/ai/05_PROJECT_CONTEXT.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _obsolete_phrases() -> list[str]:
    return [
        "业务自动派单" + "发送仍禁止",
        "sent " + "必须为 false",
        "AI 回复 auto_send " + "恒为 false",
        "reply_decision_service 全路径 " + "auto_send=False",
    ]


def test_entry_contexts_do_not_keep_obsolete_send_hard_gates():
    combined = _read(AGENTS) + "\n" + _read(PROJECT_CONTEXT)
    leaked = [phrase for phrase in _obsolete_phrases() if phrase in combined]
    assert leaked == []


def test_entry_contexts_keep_runtime_safety_boundaries():
    combined = _read(AGENTS) + "\n" + _read(PROJECT_CONTEXT)
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


def test_entry_contexts_include_phase1_confirmed_scope():
    combined = _read(AGENTS) + "\n" + _read(PROJECT_CONTEXT)
    required = [
        "AI剪辑",
        "一键过审",
        "auto_edit",
        "douyinAPI",
        "auto_wechat:ai_edit",
        "all_extracted_contacts",
        "短视频/直播留资管理表",
        "每日线索销售反馈表",
        "线索溯源表",
        "销售单车成本表",
    ]
    missing = [item for item in required if item not in combined]
    assert missing == []
```

### 执行步骤

1. 新增或更新入口上下文合同测试。
2. 运行：

```powershell
pytest tests/test_xiaogao_phase0b_entry_context_contract.py -v
```

预期：首次运行应失败，指出 `AGENTS.md` 或 `docs/ai/05_PROJECT_CONTEXT.md` 中仍有旧入口上下文。

3. 更新 `AGENTS.md` 和 `docs/ai/05_PROJECT_CONTEXT.md`。
4. 再次运行：

```powershell
pytest tests/test_xiaogao_phase0b_entry_context_contract.py -v
```

预期：通过。

5. 运行 Phase 0 合同测试，确认没有回退：

```powershell
pytest tests/test_xiaogao_phase1_context_contract.py tests/test_xiaogao_phase0b_entry_context_contract.py -v
```

预期：全部通过。

6. 运行文档格式检查：

```powershell
git diff --check -- AGENTS.md docs/ai/05_PROJECT_CONTEXT.md tests/test_xiaogao_phase1_context_contract.py tests/test_xiaogao_phase0b_entry_context_contract.py
```

预期：无输出，退出码为 0。

7. 返回阶段结果，不在本窗口提交合并决定。

## 实现子代理回传格式

```text
阶段：Phase 0-B 入口上下文残留清理
状态：DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
变更文件：
数据库迁移：无
业务逻辑改动：无
服务启动 / 真实请求：无
测试命令：
测试结果：
自审结论：
剩余风险：
需要本窗口审批的问题：
```

## Spec Reviewer 清单

Spec Reviewer 只检查是否符合需求，不做代码风格评审。

必须确认：

1. `AGENTS.md` 不再把旧自动发送硬门禁表达为当前约束。
2. `docs/ai/05_PROJECT_CONTEXT.md` 不再把旧自动发送硬门禁表达为当前约束。
3. 两个入口文件都明确：放开旧硬门禁不等于绕过后端 gate。
4. 两个入口文件都保留违禁词、人工接管、限频、失败回写、幂等、紧急停止。
5. 两个入口文件都保留微信自动化底线。
6. 两个入口文件都包含 AI剪辑、一键过审进入一期的最新范围。
7. 两个入口文件都说明 `auto_edit` 后续迁入、`douyinAPI` 仅复制改造。
8. 入口合同测试覆盖 `AGENTS.md` 和 `docs/ai/05_PROJECT_CONTEXT.md`。
9. 没有把历史验收文档或前端页面旧文案强行纳入 Phase 0-B。

Spec Reviewer 结论格式：

```text
Spec Reviewer 结论：Approved / Changes Required
问题列表：
是否允许进入代码质量评审：是 / 否
```

## Code Quality Reviewer 清单

Code Quality Reviewer 在 Spec Approved 后执行。

必须确认：

1. Phase 0-B 只修改允许范围内文件。
2. 测试是纯文本合同测试，不依赖外部服务、不启动服务、不访问网络。
3. 测试不会因为本测试文件中的拆分字符串而误判自身。
4. 文档表述能指导后续 agent，不会把旧约束误读为当前规则。
5. 没有密钥、token、新环境变量或敏感本机信息。
6. `git diff --check` 通过。
7. 没有数据库迁移、业务发送逻辑、前端交互改动。

Code Quality Reviewer 结论格式：

```text
Code Quality Reviewer 结论：Approved / Changes Required
问题列表：
剩余风险：
```

## 本窗口审批清单

本窗口收到执行结果后，按以下项目审批：

1. 执行窗口是否完整回传状态、变更文件、测试命令、测试结果、两类 reviewer 结论。
2. 是否没有数据库迁移和业务代码改动。
3. 是否没有服务启动和真实请求。
4. `AGENTS.md` 与 `docs/ai/05_PROJECT_CONTEXT.md` 是否完成旧入口上下文清理。
5. Phase 0 和 Phase 0-B 的合同测试是否全部通过。
6. 是否可以允许进入 Phase 1 数据迁移骨架。

审批结论只能是：

```text
通过：允许进入 Phase 1。
有条件通过：允许准备 Phase 1，但必须在 Phase 1 前补齐指定文档/测试问题。
不通过：返回执行窗口修复后重新评审。
```
