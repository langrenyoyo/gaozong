-- 0009 AI小高线索跟进记录最小表
-- 范围：保存首次分配、重新分配、人工备注等统一跟进记录。
-- 不修改 douyin_leads 字段，不执行商户隔离字段迁移。

CREATE TABLE IF NOT EXISTS lead_followup_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    staff_id INTEGER,
    record_type VARCHAR(30) NOT NULL,
    content TEXT,
    operator_id VARCHAR(128),
    created_at DATETIME,
    FOREIGN KEY(lead_id) REFERENCES douyin_leads(id),
    FOREIGN KEY(staff_id) REFERENCES sales_staff(id)
);

CREATE INDEX IF NOT EXISTS idx_lead_followup_records_lead_created
    ON lead_followup_records(lead_id, created_at);
