-- NewCar 外部用户首次登录自动开通的幂等保护
CREATE UNIQUE INDEX IF NOT EXISTS uk_external_merchant_bindings_active_user
    ON external_merchant_bindings(source_system, external_user_id)
    WHERE status = 'active' AND external_user_id IS NOT NULL AND external_user_id <> '';
