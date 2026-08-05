"""P-0-C 空号追问链路 块2 最小测试——contact_validity_analyzer + mark/recover_contact_valid。

只测确定性逻辑，不测 DB 连接/时序。
"""

import sys
import os
sys.path.insert(0, os.getcwd())


def test_analyze_pure_invalid():
    from app.services.contact_validity_analyzer import analyze_contact_validity
    r = analyze_contact_validity("这个号码是空号")
    assert r.status == "invalid"
    assert r.reason == "empty_number"


def test_analyze_pure_invalid_wechat():
    from app.services.contact_validity_analyzer import analyze_contact_validity
    r = analyze_contact_validity("微信加不上")
    assert r.status == "invalid"
    assert r.reason == "wechat_add_failed"


def test_analyze_pure_recovery():
    from app.services.contact_validity_analyzer import analyze_contact_validity
    r = analyze_contact_validity("号码没问题，已经联系上了")
    assert r.status == "valid"


def test_analyze_conflict_returns_unknown():
    from app.services.contact_validity_analyzer import analyze_contact_validity
    r = analyze_contact_validity("不是空号，但打不通")
    assert r.status == "unknown"


def test_analyze_no_match_returns_unknown():
    from app.services.contact_validity_analyzer import analyze_contact_validity
    r = analyze_contact_validity("好的，我知道了")
    assert r.status == "unknown"


def test_analyze_empty_returns_unknown():
    from app.services.contact_validity_analyzer import analyze_contact_validity
    r = analyze_contact_validity("")
    assert r.status == "unknown"
    r2 = analyze_contact_validity(None)
    assert r2.status == "unknown"


def test_analyze_customer_denied():
    from app.services.contact_validity_analyzer import analyze_contact_validity
    r = analyze_contact_validity("客户不接")
    assert r.status == "invalid"
    assert r.reason == "customer_denied"


def test_analyze_recovery_overrides_invalid():
    from app.services.contact_validity_analyzer import analyze_contact_validity
    # "已经联系上了" 含恢复词，即使有"联系不上"的子串也应优先恢复
    r = analyze_contact_validity("已经联系上了")
    assert r.status == "valid"
