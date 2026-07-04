# P1-NEWCAR-MERCHANT-AUTO-PROVISION-1

## 1. 任务目标

解决 NewCarProject 新建商户账号首次登录 auto_wechat 时，因为 NewCar 当前不下发 `merchant_id`，导致 `/auth/me` 返回 `EXTERNAL_MERCHANT_NOT_BOUND` 的问题。

本轮只在 auto_wechat 内部补齐本地商户空间自动开通能力，不修改 NewCarProject 服务端，不修改对外 schema，不触发真实发送、真实 LLM、真实 Milvus 或抖音上游调用。

## 2. 背景

当前 NewCarProject `/external-auth/me` 返回中，商户账号可能出现：

```text
merchant_id=null
merchant_ids=[]
```

这是上游历史设计状态。NewCarProject 负责账号、登录和权限勾选；auto_wechat 负责本地 `merchant_id` 与业务数据隔离。

因此，auto_wechat 不能继续要求商户侧账号必须由 NewCar 返回 `merchant_id`，而应在确认该账号拥有商户侧权限后，创建或复用本地商户绑定。

## 3. 本地 merchant_id 生成规则

实现位置：

```text
app/auth/external_merchant_binding_service.py
```

生成规则：

```text
merchant_id = "m_nc_" + sha256("new_car_project:" + external_user_id).hexdigest()[:16]
```

约束：

1. 同一个 `external_user_id` 始终生成同一个 `merchant_id`。
2. 不使用 `username` / `external_account` 参与生成。
3. 不把手机号、账号名或原始 `external_user_id` 拼进 `merchant_id`。
4. `external_user_id` 缺失时拒绝自动生成，不用 `username` 兜底。

## 4. 权限分类

商户侧权限：

```text
auto_wechat:douyin_ai_cs
auto_wechat:leads
auto_wechat:agent
auto_wechat:compute
auto_wechat:ai_edit
```

管理员侧权限：

```text
auto_wechat:admin:*
```

处理规则：

1. admin-only 账号：允许 `/auth/me` 返回 200，`merchant_id` 可为空，不创建本地商户绑定。
2. merchant 账号：优先复用 active 绑定；无 active 绑定时自动创建本地 `merchant_id`。
3. admin + merchant 账号：创建或复用本地 `merchant_id`，方便进入商户侧页面；管理员页面仍不依赖 `merchant_id`。
4. 只有 `auto_wechat:use` 的账号：不创建 `merchant_id`，继续保持无商户绑定错误。

## 5. 绑定表与幂等策略

复用现有表：

```text
external_merchant_bindings
```

本轮新增迁移：

```text
migrations/versions/0026_external_merchant_bindings_unique_active_user.sql
```

新增约束：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uk_external_merchant_bindings_active_user
    ON external_merchant_bindings(source_system, external_user_id)
    WHERE status = 'active' AND external_user_id IS NOT NULL AND external_user_id <> '';
```

幂等策略：

1. 同一个 `source_system + external_user_id` 已有 active 绑定时直接复用。
2. 已有 disabled / deleted 绑定时不静默复活，返回明确错误。
3. 并发首次登录时，通过 active 唯一索引兜底；若插入遇到唯一约束冲突，则回读已创建的 active 绑定。
4. `external_account` 只作为快照字段保存，不参与 `merchant_id` 生成。

## 6. 接入点

接入位置：

```text
app/auth/dependencies.py
```

调用链：

```text
/auth/me
  -> get_request_context_required
  -> _resolve_required_context
  -> _with_local_merchant_binding
  -> get_or_create_newcar_merchant_binding
  -> external_merchant_bindings
```

`RequestContext` 新增商户侧权限判断：

```text
app/auth/context.py
```

## 7. 当前 P1 限制

1. 当前是一名 NewCar 用户对应一个 auto_wechat 本地 merchant space。
2. 不处理多个 NewCar 用户归并到同一商户的业务合并。
3. 不新增人工绑定后台。
4. 不修改 NewCarProject 服务端。
5. 不信任前端传入的 `merchant_id`。

后续如果需要多账号同商户，应新增显式绑定 / 合并流程，并保留审计日志，不能靠 username 或手机号自动合并。

## 8. 测试覆盖

新增测试：

```text
tests/test_newcar_merchant_auto_provision.py
```

覆盖场景：

1. 商户权限 + 无本地绑定时自动创建 `merchant_id`。
2. 已有 active 绑定时复用，不重复创建。
3. 同一 `external_user_id` 的 username 变化时 `merchant_id` 不变。
4. admin-only 不创建 `merchant_id`。
5. admin + merchant 会自动创建 / 复用 `merchant_id`。
6. 只有 `auto_wechat:use` 不创建商户空间。
7. 缺失 `external_user_id` 不使用 username 兜底。
8. 生成的 `merchant_id` 不泄露 raw user id。
9. disabled 绑定不静默复活。

迁移测试：

```text
tests/test_db_migration_runner.py
```

覆盖 `0026` partial unique index 存在、重复 active 绑定被拒绝、disabled 同 user 可保留、迁移版本落入 `schema_migrations`。

## 9. 未改内容

本轮未修改：

1. NewCarProject 服务端。
2. `/auth/me` 响应 schema。
3. 前端路由和菜单。
4. 自动回复真实发送 gate。
5. 微信 Local Agent、live-check、19000。
6. 真实抖音发送上游。
7. 真实 LLM。
8. 真实 Milvus。

## 10. 后续建议

1. 用真实 NewCar 商户账号复测 `/auth/me`，确认 `merchant_id` 自动生成且不再返回 `EXTERNAL_MERCHANT_NOT_BOUND`。
2. 如果需要多个 NewCar 用户共享同一商户空间，单独设计人工绑定 / 合并流程。
3. 后续可补充管理员只读诊断页，展示脱敏后的绑定状态和权限码，便于排查首登问题。
