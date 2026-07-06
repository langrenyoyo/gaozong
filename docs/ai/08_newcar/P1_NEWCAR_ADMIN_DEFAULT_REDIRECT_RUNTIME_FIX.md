# P1-NEWCAR-ADMIN-DEFAULT-REDIRECT-RUNTIME-FIX-1

## 1. 目标

修复 NewCar 管理员账号真实登录后仍先进入 `/douyin-cs/workbench` 的运行时问题。

管理员账号具备 `auto_wechat:admin:autoreply` 时，登录后默认应进入：

```text
/admin/autoreply-rollout
```

本轮只修前端登录后跳转、redirect 候选路径校验与本地 redirect 清理，不改 NewCarProject 服务端，不改商户自动开通规则，不改自动回复真实发送 gate。

## 2. 真实现象

已知运行态现象：

1. NewCar 管理员账号登录后先进入 `/douyin-cs/workbench`。
2. 页面内点击“返回工作台”后可进入 `/admin/autoreply-rollout`。
3. `/api/auth/me = 200`。
4. `/api/admin/autoreply/rollout/summary = 200`。
5. logout 已能跳回 NewCar 登录页。

这说明后端权限链路和 admin API 可用，问题集中在前端登录后默认跳转、redirect 缓存或 fallback 逻辑。

## 3. 根因

前端 `frontend/src/newcarRedirect.ts` 原先存在两个问题：

1. `DEFAULT_POST_LOGIN_PATH` 固定为 `/douyin-cs/workbench`。
2. `App.tsx` 在 code exchange 成功后，先调用 `restoreSavedRedirectPathAfterLogin()` 修改浏览器路径，再构造 `nextUser` 和读取 `permission_codes`。

因此，redirect 只经过站内 allowlist，没有经过当前登录用户的权限校验。管理员账号即使具备 `auto_wechat:admin:autoreply`，也可能被旧 fallback 或旧缓存带到商户客服工作台。

## 4. redirect 候选来源

本轮保留并约束现有来源：

1. `sessionStorage.newcar_redirect_path`：由跳转 NewCar 登录前保存。
2. `sessionStorage.newcar_redirect_path_saved_at`：用于 TTL 校验。
3. 代码默认 fallback：现在只回到 `/`，最终首页由 `App.tsx` 按当前用户权限计算。

未发现项目内使用 `redirect_after_login`、`newcar_redirect_after_login`、`post_login_redirect` 等其它 key。

## 5. 权限校验规则

登录后统一走 `resolvePostLoginPath(user, candidateRedirect)`：

1. candidateRedirect 必须是站内路径。
2. candidateRedirect 必须先通过 `newcarRedirect.ts` 的 allowlist。
3. candidateRedirect 必须满足当前用户权限。
4. 无权限时丢弃 candidateRedirect，并重新计算默认首页。
5. redirect 被消费、过期或拒绝后都会清理本地缓存。

关键路径权限：

```text
/admin/autoreply-rollout -> super_admin 或 auto_wechat:admin:autoreply
/admin/ai-reply-records -> super_admin 或 auto_wechat:admin:ai_reply_records
/douyin-cs/workbench -> auto_wechat:douyin_ai_cs
/leads -> auto_wechat:leads
/compute/center -> auto_wechat:compute
/agents、/wechat-assistant -> auto_wechat:agent
```

## 6. 默认首页优先级

无有效 redirect 时：

1. `super_admin` 或 `auto_wechat:admin:autoreply` -> `/admin/autoreply-rollout`
2. `auto_wechat:admin:ai_reply_records` -> `/admin/ai-reply-records`
3. `auto_wechat:admin:return_visit_prompts` -> `/admin/no-local-feature`
4. `auto_wechat:admin:accounts` / `auto_wechat:admin:forbidden_words` -> `/admin/newcar-owned`
5. 商户侧权限按能力中心顺序进入对应商户页面
6. 仅有 `auto_wechat:use` -> `/`

## 7. admin-only 规则

admin-only 账号不再强制要求 `auto_wechat:use` 才能进入前端。

admin-only 账号仍不会进入商户页面：

1. 不要求 `merchant_id`。
2. 不进入 `/douyin-cs/workbench`。
3. 不触发商户页面初始化。
4. 有 `auto_wechat:admin:autoreply` 时默认进入 `/admin/autoreply-rollout`。
5. 只有 NewCarProject 归属 admin 权限时进入本地提示页。

## 8. admin + merchant 规则

同时具备 admin 与 merchant 权限时：

1. 无 redirect 时优先进入 admin 默认页。
2. 显式 redirect 指向有权限的商户页时允许进入。
3. 显式 redirect 指向无权限页面时丢弃，并回到权限化默认首页。

## 9. redirect 清理时机

以下场景会清理 NewCar redirect 状态：

1. logout。
2. 重新登录。
3. code exchange 成功后消费 redirect。
4. redirect 过期。
5. redirect 不在 allowlist。
6. redirect 被权限化解析丢弃后不会再次残留。

## 10. 测试

本轮新增：

```text
frontend/scripts/check-newcar-admin-default-redirect-runtime.mjs
npm run newcar-admin-redirect:check
```

覆盖：

1. `admin:autoreply` 默认进入 `/admin/autoreply-rollout`。
2. admin-only 不要求商户 `auto_wechat:use`。
3. code 登录后先拿到用户权限，再解析 redirect。
4. 无权 redirect 不会直接进入 `/douyin-cs/workbench`。
5. `admin:ai_reply_records`、`admin:return_visit_prompts` 不等同于 `admin:autoreply`。
6. 不出现 `force_send` / `bypass` / `ignore_gate` / `set_final_auto_send`。

## 11. 未改内容

本轮未修改：

1. NewCarProject 服务端。
2. 商户自动开通规则。
3. 9000 对外 schema。
4. 自动回复真实发送 gate。
5. 真实抖音发送上游。
6. 真实 LLM。
7. 真实 Milvus。
8. Local Agent / live-check / 19000。

## 12. 真实浏览器 E2E 建议

使用 NewCar 管理员账号：

1. 清理浏览器 `sessionStorage` / `localStorage` 中的 token 和 redirect 相关 key。
2. 从 NewCarProject 登录。
3. 跳回 auto_wechat。
4. 预期直接进入 `/admin/autoreply-rollout`。
5. Network 确认 `/api/auth/me = 200`。
6. Network 确认 `/api/admin/autoreply/rollout/summary = 200`。
7. 确认没有先进入 `/douyin-cs/workbench`。
8. 点击退出登录，确认跳回 `VITE_NEWCAR_LOGIN_URL`。

商户账号回归：

1. 具备 `auto_wechat:use` + `auto_wechat:douyin_ai_cs`。
2. 登录后进入 `/douyin-cs/workbench`。
3. `/api/auth/me = 200`。
4. 不出现 `EXTERNAL_MERCHANT_NOT_BOUND`。

全程不得输出 token、cookie、secret。
