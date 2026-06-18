-- 0010 小高算力一期基础表
-- ============================================================================
-- 范围：商户 Token 账户、Token 流水、Token 套餐三张表（纯新增，不改现有 14 张表）。
-- 对齐《小高AI系统需求文档（一期）》：
--   - 2.7 小高算力（/compute）：余额、今日/昨日/累计消耗、Token 明细、充值套餐
--   - 3.1 商户管理：算力余额列、给商户充值、给商户发放套餐
--   - 3.5 算力配置：套餐名称、价格、Token 数量、启用/禁用
-- 字段口径：
--   - balance_tokens / delta_tokens / balance_after_tokens / token_amount 均为整数 Token，不用浮点
--   - price_yuan 为整数元（一期套餐 99/299/699 均为整数元），不引入 Decimal/Numeric
--   - transaction_type / source 为受控字符串，取值约束在 service 层
--   - model / agent_id / conversation_id 本轮允许 NULL，预留给后续 AI 消耗埋点（USAGE-1）
-- 本轮不做：
--   - API / service / 前端 / 真实支付 / 余额拦截 / 复杂 billing / 默认套餐 seed
-- 幂等：全部 CREATE TABLE / CREATE INDEX 使用 IF NOT EXISTS（SQLite 原生支持）
-- ============================================================================

-- 1. 商户 Token 账户表：一个商户一行，记录当前可用余额
CREATE TABLE IF NOT EXISTS compute_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128),
    balance_tokens INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_compute_accounts_merchant
    ON compute_accounts(merchant_id);

-- 2. Token 流水表：充值 / 消耗 / 套餐发放记录，支撑 Token 明细与今日/昨日/累计消耗
CREATE TABLE IF NOT EXISTS compute_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128),
    transaction_type VARCHAR(32) NOT NULL,
    delta_tokens INTEGER NOT NULL,
    balance_after_tokens INTEGER NOT NULL,
    source VARCHAR(32) NOT NULL,
    remark TEXT,
    model VARCHAR(128),
    agent_id VARCHAR(64),
    conversation_id INTEGER,
    created_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_compute_transactions_merchant_created
    ON compute_transactions(merchant_id, created_at);

-- 3. Token 套餐表：管理员算力配置 + 商户充值弹窗套餐展示
CREATE TABLE IF NOT EXISTS compute_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    price_yuan INTEGER NOT NULL,
    token_amount INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME
);
