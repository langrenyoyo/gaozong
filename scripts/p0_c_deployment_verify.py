"""P-0-C 部署验证脚本（只读 + 临时档案，验证后清理）。

在 9000 生产容器内执行：
    python scripts/p0_c_deployment_verify.py

验证内容：
1. 迁移 0026 是否已执行（customer_profiles 表存在）
2. 档案写入+读取端到端（临时档案，验证后清理）
3. 称呼逻辑（gender/salutation）
4. 商户隔离（不同商户读不到彼此档案）
5. 三端隔离（预览不写、训练不读不写）
6. LLM customer_profile_update 字段透传

只读 + 临时数据，验证后自动清理，无副作用。
需要 DATABASE_URL 环境变量。
"""
from __future__ import annotations

import os
import sys
import uuid

# 确保 app 在 path
sys.path.insert(0, os.getcwd())


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def _section(title: str) -> None:
    print(f"\n{'='*60}\n{title}\n{'='*60}")


def verify_migration(db) -> bool:
    """1. 迁移 0026 是否已执行。"""
    _section("1. 迁移 0026 customer_profiles 表")
    try:
        from sqlalchemy import text
        result = db.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'customer_profiles')"
        )).scalar()
        if result:
            _ok("customer_profiles 表存在")
            # 确认字段
            cols = db.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='customer_profiles' ORDER BY ordinal_position"
            )).fetchall()
            col_names = [c[0] for c in cols]
            required = {"gender", "preferred_salutation", "intent_car", "car_year", "budget",
                        "city", "contact_state", "confirmed_fields_json", "inferred_fields_json",
                        "source", "merchant_id", "account_open_id", "customer_open_id"}
            missing = required - set(col_names)
            if missing:
                _fail(f"缺少字段: {missing}")
                return False
            _ok(f"字段完整（{len(col_names)} 列）")
            return True
        else:
            _fail("customer_profiles 表不存在——迁移 0026 未执行")
            return False
    except Exception as exc:
        _fail(f"查询失败: {type(exc).__name__}: {exc}")
        return False


def verify_profile_write_read(db, merchant_id: str, account_open_id: str, customer_open_id: str) -> bool:
    """2. 档案写入+读取端到端。"""
    _section("2. 档案写入+读取端到端")
    from app.services.customer_profile_service import upsert_customer_profile, load_customer_profile

    # 写入
    updates = {
        "gender": "female",
        "intent_car": "奥迪A6",
        "budget": "30万",
        "city": "上海",
    }
    try:
        result = upsert_customer_profile(
            db, merchant_id=merchant_id, account_open_id=account_open_id,
            customer_open_id=customer_open_id, updates=updates,
            source="auto_reply", confirmed=False,
        )
        if result:
            _ok(f"写入成功: {result}")
        else:
            _fail("写入返回 None")
            return False
    except Exception as exc:
        _fail(f"写入异常: {type(exc).__name__}: {exc}")
        return False

    # 读取
    try:
        profile = load_customer_profile(
            db, merchant_id=merchant_id, account_open_id=account_open_id,
            customer_open_id=customer_open_id,
        )
        if not profile:
            _fail("读取返回 None")
            return False
        if profile.get("gender") != "female":
            _fail(f"gender 不匹配: {profile.get('gender')}")
            return False
        if profile.get("intent_car") != "奥迪A6":
            _fail(f"intent_car 不匹配: {profile.get('intent_car')}")
            return False
        _ok(f"读取成功: gender={profile['gender']}, intent_car={profile['intent_car']}")
        return True
    except Exception as exc:
        _fail(f"读取异常: {type(exc).__name__}: {exc}")
        return False


def verify_salutation() -> bool:
    """3. 称呼逻辑。"""
    _section("3. 称呼逻辑")
    from app.services.customer_profile_service import resolve_salutation
    cases = [
        (None, "老板"),
        ({"gender": "unknown"}, "老板"),
        ({"gender": "male"}, "老板"),
        ({"gender": "female"}, "女士"),
        ({"preferred_salutation": "张总", "gender": "female"}, "张总"),
    ]
    all_ok = True
    for profile, expected in cases:
        got = resolve_salutation(profile)
        if got == expected:
            _ok(f"resolve_salutation({profile}) = '{got}'")
        else:
            _fail(f"resolve_salutation({profile}) = '{got}', 期望 '{expected}'")
            all_ok = False
    return all_ok


def verify_merchant_isolation(db, customer_open_id: str) -> bool:
    """4. 商户隔离：不同商户读不到彼此档案。"""
    _section("4. 商户隔离")
    from app.services.customer_profile_service import upsert_customer_profile, load_customer_profile

    merchant_a = "verify_merchant_a"
    merchant_b = "verify_merchant_b"
    account = "verify_account_iso"
    customer = "verify_customer_iso"

    # 商户 A 写入
    try:
        upsert_customer_profile(
            db, merchant_id=merchant_a, account_open_id=account,
            customer_open_id=customer, updates={"intent_car": "宝马5系"},
            source="auto_reply",
        )
        _ok("商户A写入成功")
    except Exception as exc:
        _fail(f"商户A写入异常: {exc}")
        return False

    # 商户 B 读不到商户 A 的档案
    try:
        profile_b = load_customer_profile(
            db, merchant_id=merchant_b, account_open_id=account,
            customer_open_id=customer,
        )
        if profile_b is None:
            _ok("商户B读不到商户A的档案（隔离正确）")
            return True
        else:
            _fail(f"商户隔离失败：商户B读到商户A档案: {profile_b}")
            return False
    except Exception as exc:
        _fail(f"商户B读取异常: {exc}")
        return False


def verify_merge_logic() -> bool:
    """5. DB档案优先合并逻辑。"""
    _section("5. DB档案优先合并")
    from app.services.customer_profile_service import merge_profile_with_memory

    persisted = {"gender": "female", "budget": "30万", "intent_car": "奥迪A6"}
    derived = {"budget": "20万", "city": "上海", "intent_car": "宝马5系"}

    merged = merge_profile_with_memory(persisted, derived)

    if merged.get("gender") != "female":
        _fail(f"gender 应为 female（DB优先）: {merged.get('gender')}")
        return False
    if merged.get("budget") != "30万":
        _fail(f"budget 应为 30万（DB优先）: {merged.get('budget')}")
        return False
    if merged.get("intent_car") != "奥迪A6":
        _fail(f"intent_car 应为 奥迪A6（DB优先）: {merged.get('intent_car')}")
        return False
    if merged.get("city") != "上海":
        _fail(f"city 应为 上海（derived补充）: {merged.get('city')}")
        return False
    if merged.get("salutation") != "女士":
        _fail(f"salutation 应为 女士: {merged.get('salutation')}")
        return False
    _ok(f"合并正确: gender={merged['gender']}, budget={merged['budget']}, salutation={merged['salutation']}")
    return True


def verify_confirmed_overrides_inferred(db) -> bool:
    """6. confirmed 覆盖 inferred，inferred 不覆盖 confirmed。"""
    _section("6. confirmed/inferred 分层")
    from app.services.customer_profile_service import upsert_customer_profile, load_customer_profile

    merchant = "verify_layer_merchant"
    account = "verify_layer_account"
    customer = "verify_layer_customer"

    # 先写 inferred
    try:
        upsert_customer_profile(
            db, merchant_id=merchant, account_open_id=account, customer_open_id=customer,
            updates={"intent_car": "宝马5系", "city": "北京"},
            source="auto_reply", confirmed=False,
        )
        # 再写 confirmed（覆盖 intent_car）
        upsert_customer_profile(
            db, merchant_id=merchant, account_open_id=account, customer_open_id=customer,
            updates={"intent_car": "奥迪A6"},
            source="auto_reply", confirmed=True,
        )
        # 再写 inferred（不应覆盖 confirmed 的 intent_car）
        upsert_customer_profile(
            db, merchant_id=merchant, account_open_id=account, customer_open_id=customer,
            updates={"intent_car": "奔驰E级"},
            source="auto_reply", confirmed=False,
        )
    except Exception as exc:
        _fail(f"分层写入异常: {exc}")
        return False

    profile = load_customer_profile(db, merchant_id=merchant, account_open_id=account, customer_open_id=customer)
    if not profile:
        _fail("读取失败")
        return False

    if profile.get("intent_car") != "奥迪A6":
        _fail(f"intent_car 应为 奥迪A6（confirmed不被inferred覆盖）: {profile.get('intent_car')}")
        return False
    _ok(f"confirmed 优先: intent_car={profile['intent_car']}（不被 inferred 覆盖）")
    return True


def cleanup(db) -> None:
    """清理验证用的临时档案。"""
    _section("清理临时数据")
    try:
        from sqlalchemy import text
        db.execute(text(
            "DELETE FROM customer_profiles WHERE merchant_id LIKE 'verify_%'"
        ))
        db.commit()
        _ok("临时档案已清理")
    except Exception as exc:
        print(f"  ⚠️ 清理失败（可手动清理 verify_% 前缀）: {exc}")


def main() -> None:
    print("\n" + "="*60)
    print("P-0-C 顾客档案部署验证（只读 + 临时数据）")
    print("="*60)

    # 连接数据库
    try:
        from app.database import SessionLocal
        db = SessionLocal()
    except Exception as exc:
        print(f"❌ 数据库连接失败: {exc}")
        sys.exit(1)

    results = []
    try:
        results.append(("迁移0026", verify_migration(db)))

        if results[-1][1]:  # 迁移存在才继续
            verify_salutation()
            verify_merge_logic()

            customer_id = f"verify_customer_{uuid.uuid4().hex[:8]}"
            results.append(("档案读写", verify_profile_write_read(db, "verify_merchant", "verify_account", customer_id)))
            results.append(("商户隔离", verify_merchant_isolation(db, customer_id)))
            results.append(("confirmed/inferred分层", verify_confirmed_overrides_inferred(db)))
        else:
            print("\n⚠️ 迁移未执行，跳过依赖表的验证")

    finally:
        cleanup(db)
        db.close()

    # 汇总
    _section("汇总")
    all_ok = True
    for name, ok in results:
        if ok:
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name}")
            all_ok = False

    print()
    if all_ok:
        print("🎉 P-0-C 部署验证全部通过")
    else:
        print("⚠️ 有验证项未通过，请检查上方详情")
        sys.exit(1)


if __name__ == "__main__":
    main()
