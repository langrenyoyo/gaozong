"""R1：商户改密与管理员退出鉴权状态契约静态回归。

前端无单元测试框架，沿用既有静态源码解析模式（见 test_frontend_capability_navigation.py），
断言 auth.ts / App.tsx 的错误类别判定、成功白名单、管理员退出 token 流转、handleRelogin 状态清理
等关键代码契约，确保 R1 返修要求在源码层可判定。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


AUTH_TS = _read("frontend/src/api/auth.ts")
APP_TSX = _read("frontend/src/App.tsx")


def _find_block(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


# ---------------------------------------------------------------------------
# R1-2/3/4：改密 API 返回结构化错误类别，严格成功白名单
# ---------------------------------------------------------------------------


def test_change_external_password_returns_structured_outcome():
    """changeExternalPassword 必须返回四态 outcome，而非抛文案异常（避免靠文案匹配判定类别）。"""
    assert "ChangeExternalPasswordOutcome" in AUTH_TS
    assert '{ status: "success"' in AUTH_TS
    assert '{ status: "business"' in AUTH_TS
    assert '{ status: "relogin"' in AUTH_TS
    assert '{ status: "unknown"' in AUTH_TS


def test_change_external_password_success_strict_whitelist():
    """R1-4：成功必须严格匹配 ok===true && relogin_required===true && revoked_session_scope==='all'。"""
    block = _find_block(AUTH_TS, "data.ok === true", "return { status:")
    assert "data.ok === true" in block
    assert "data.relogin_required === true" in block
    assert 'data.revoked_session_scope === "all"' in block
    # 2xx 但不符白名单按结果未知处理，不得当作成功。
    assert 'status: "unknown"' in _find_block(AUTH_TS, "isStrictSuccess", "return { status: \"success\"")


def test_change_external_password_timeout_is_unknown():
    """R1-3：超时/网络中断为结果未知，不得抛异常或当作业务失败。"""
    # changeExternalPassword 的 fetch try/catch：catch 块返回 unknown
    fn_block = _find_block(AUTH_TS, "export async function changeExternalPassword", "export async function logoutCurrentBrowserOnNewCar")
    # fetch 调用后紧跟 catch
    fetch_idx = fn_block.index("await fetch(")
    after_fetch = fn_block[fetch_idx:]
    catch_start = after_fetch.index("} catch {")
    catch_end = after_fetch.index("}", catch_start + len("} catch {"))
    catch_block = after_fetch[catch_start:catch_end + 1]
    assert 'status: "unknown"' in catch_block
    # 超时不抛异常（不出现 throw）
    assert "throw new Error" not in catch_block


def test_change_external_password_5xx_and_bad_json_are_unknown():
    """R1-3：5xx、非 2xx、异常 JSON 都按结果未知处理。"""
    block = _find_block(AUTH_TS, "jsonParseFailed = false", "return { status: \"success\"")
    assert "response.status === 401" in block
    assert "response.status === 400" in block
    # 5xx/其他非 2xx 与异常 JSON 走 unknown
    assert '!response.ok || jsonParseFailed' in block
    assert 'status: "unknown"' in block


def test_change_external_password_401_is_relogin():
    """R1-2：401 为重新登录类别，与业务失败区分。"""
    block = _find_block(AUTH_TS, "if (response.status === 401)", "if (response.status === 400")
    assert 'status: "relogin"' in block


def test_change_external_password_400_403_is_business():
    """R1-2：400/403 为业务失败类别，保留登录态。"""
    block = _find_block(AUTH_TS, "if (response.status === 400 || response.status === 403)", "if (!response.ok")
    assert 'status: "business"' in block


# ---------------------------------------------------------------------------
# R1-1：管理员退出接收显式 token，首次读存储、重试用内存 ref
# ---------------------------------------------------------------------------


def test_admin_logout_internal_function_takes_explicit_token():
    """performAdminLogout 必须接收显式 token 参数，而非内部读存储。"""
    assert "const performAdminLogout = async (token: string | null)" in APP_TSX


def test_admin_logout_first_call_reads_storage():
    """首次调用从存储读取 token 传入。"""
    assert "void performAdminLogout(getExternalToken())" in APP_TSX


def test_admin_logout_retry_uses_memory_ref_not_storage():
    """R1-7 关键：重试必须直接使用 adminLogoutTokenRef.current，不得再次读取存储或覆盖为空。"""
    block = _find_block(APP_TSX, "const retryAdminLogout = () => {", "  };\n\n  const handleBackToWorkbench")
    # 重试分支使用 ref，不调用 getExternalToken()
    assert "performAdminLogout(adminLogoutTokenRef.current)" in block
    # 重试函数体内不得调用 getExternalToken（必须用内存 token，不重新读存储）
    assert "getExternalToken()" not in block


def test_admin_logout_stores_token_to_ref_before_request():
    """首次调用在发请求前把 token 存入 ref，供失败后重试使用。"""
    block = _find_block(APP_TSX, "const performAdminLogout = async", "  const handleAdminLogout = () =>")
    assert "adminLogoutTokenRef.current = token" in block
    # 先存 ref 再置 loading
    assert block.index("adminLogoutTokenRef.current = token") < block.index("setAdminLoggingOut(true)")


def test_admin_logout_failure_keeps_memory_token_for_retry():
    """失败分支不清空内存 token，保留供重试（成功分支才清空）。"""
    block = _find_block(APP_TSX, "const performAdminLogout = async", "  const handleAdminLogout = () =>")
    # 定位 catch 块（失败分支），其范围从 "} catch {" 到下一个 "} finally"
    catch_start = block.index("} catch {")
    finally_start = block.index("} finally {", catch_start)
    catch_block = block[catch_start:finally_start]
    # 失败分支不清 adminLogoutTokenRef.current（保留供重试）
    assert "adminLogoutTokenRef.current = null" not in catch_block
    # 失败分支清本地持久状态、设置错误提示、不跳错系统
    assert "clearLocalPersistentAuthState()" in catch_block
    assert "setAdminLogoutError(" in catch_block
    assert "redirectToNewCarLogin" not in catch_block
    # 成功分支才清 ref
    success_block = block[:catch_start]
    assert "adminLogoutTokenRef.current = null" in success_block


# ---------------------------------------------------------------------------
# R1-3/6：改密结果未知与重登录都清本地状态；handleRelogin 清全部 P4 状态
# ---------------------------------------------------------------------------


def test_change_password_success_sets_success_state():
    """R2：成功进入 success 状态页（只有 success 可展示“密码已修改”）。"""
    block = _find_block(APP_TSX, "if (outcome.status === \"success\")", "if (outcome.status === \"business\")")
    assert "clearLocalPersistentAuthState()" in block
    assert "setUser(null)" in block
    assert 'setPasswordResultView("success")' in block


def test_change_password_relogin_sets_relogin_state():
    """R2：401 进入 relogin 状态页，清本地、卸载受保护页，不得声称密码已修改。"""
    block = _find_block(APP_TSX, "if (outcome.status === \"relogin\")", "// unknown")
    assert "clearLocalPersistentAuthState()" in block
    assert "setUser(null)" in block
    assert 'setPasswordResultView("relogin")' in block
    # relogin 分支不得写 success 状态
    assert 'setPasswordResultView("success")' not in block


def test_change_password_unknown_sets_unknown_state():
    """R2：超时/网络/5xx/异常/非白名单进入 unknown 状态页，不得声称成功或失败。"""
    # unknown 分支：从注释到 finally，clearLocalPersistentAuthState 在 setter 之前。
    block = _find_block(APP_TSX, "// unknown（超时/网络", "  } finally {")
    assert "clearLocalPersistentAuthState()" in block
    assert "setUser(null)" in block
    assert 'setPasswordResultView("unknown")' in block
    # unknown 分支不得写 success/relogin 状态
    assert 'setPasswordResultView("success")' not in block
    assert 'setPasswordResultView("relogin")' not in block


def test_change_password_business_keeps_session():
    """R1-2：业务失败保留登录态、恢复 401 跳转、弹窗内重试。"""
    block = _find_block(APP_TSX, 'if (outcome.status === "business")', "if (outcome.status === \"relogin\")")
    assert "setNewCarAuthRedirectSuppressed(false)" in block
    assert "setChangePasswordError(outcome.message)" in block
    # 业务失败不清 user、不进结果状态页
    assert "setPasswordResultView(" not in block
    assert "clearLocalPersistentAuthState()" not in block


def test_change_password_result_state_type_is_four_state_enum():
    """R2：改密结果状态用四态枚举，不再用布尔 passwordReloginView。"""
    assert 'type PasswordResultView = "success" | "relogin" | "unknown"' in APP_TSX
    assert "passwordResultView" in APP_TSX
    # 旧布尔状态名必须彻底移除
    assert "passwordReloginView" not in APP_TSX
    assert "setPasswordReloginView" not in APP_TSX


def test_change_password_page_text_differs_per_state():
    """R2-9：success/relogin/unknown 三态页面文案互不相同且语义对齐。"""
    success_title = "密码已修改，请重新登录"
    relogin_title = "登录已失效，请重新登录"
    unknown_title = "密码修改结果未知，请重新登录确认"
    # 三态标题文案均在源码中存在。
    for title in (success_title, relogin_title, unknown_title):
        assert title in APP_TSX, f"缺少结果状态页文案 {title}"
    # 三态文案互不相同。
    assert len({success_title, relogin_title, unknown_title}) == 3
    # relogin 标题到 unknown 标题之间不得出现 success 标题文案（relogin 不得声称密码已修改）。
    relogin_idx = APP_TSX.index(relogin_title)
    unknown_idx = APP_TSX.index(unknown_title)
    assert success_title not in APP_TSX[relogin_idx:unknown_idx]
    # unknown 标题之后 200 字符内不得出现 success 标题文案（unknown 不得声称成功或失败）。
    assert success_title not in APP_TSX[unknown_idx:unknown_idx + 200]


def test_handle_relogin_clears_all_p4_state_and_refs():
    """R1-6：handleRelogin 必须清全部 P4 状态和内存 ref。"""
    block = _find_block(APP_TSX, "const handleRelogin = () => {", "void redirectToNewCarLogin")
    for setter in [
        'setChangePasswordOpen(false)',
        'setChangingPassword(false)',
        'setChangePasswordError(null)',
        'setPasswordResultView(null)',
        'setAdminLoggingOut(false)',
        'setAdminLogoutError(null)',
        'adminLogoutTokenRef.current = null',
        'setLogoutViewState("idle")',
        'logoutRetryTokenRef.current = null',
    ]:
        assert setter in block, f"handleRelogin 缺少清理 {setter}"


def test_admin_logout_failure_does_not_recover_old_session():
    """R1-3：管理员退出失败清本地持久状态、停留当前页，不恢复旧会话、不跳错系统。"""
    block = _find_block(APP_TSX, "const performAdminLogout = async", "void performAdminLogout(getExternalToken())")
    catch_block = block[block.index("} catch {"):]
    assert "clearLocalPersistentAuthState()" in catch_block
    assert "setAdminLogoutError(" in catch_block
    # 失败不调用 redirectToNewCarLogin（不跳错系统）
    assert "redirectToNewCarLogin" not in catch_block
