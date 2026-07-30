-- 0041 回访动态场景配置 + 跟进 SLA 任务表
-- 1. return_visit_prompts 加 6 列，默认空保持三键行为不变
-- 2. 回填三键 scene_description，trigger_source_type 默认 writeback
-- 3. 新建 return_visit_followup_tasks 表
-- 与 PG 0021 迁移同步。

ALTER TABLE return_visit_prompts ADD COLUMN scene_description TEXT;
ALTER TABLE return_visit_prompts ADD COLUMN action_type VARCHAR(32);
ALTER TABLE return_visit_prompts ADD COLUMN action_payload_json TEXT;
ALTER TABLE return_visit_prompts ADD COLUMN silence_hours INTEGER;
ALTER TABLE return_visit_prompts ADD COLUMN trigger_source_type VARCHAR(32);
ALTER TABLE return_visit_prompts ADD COLUMN cooldown_hours INTEGER;

UPDATE return_visit_prompts SET scene_description = '留资联系方式无效需重新留资：客户留资后联系方式无效或缺失，需重新确认并留资。', trigger_source_type = COALESCE(trigger_source_type, 'writeback') WHERE prompt_key = 'retain_contact_conversion' AND scene_description IS NULL;
UPDATE return_visit_prompts SET scene_description = '金融方案跟进：客户对金融/贷款方案有疑问或待跟进，需提供方案信息。', trigger_source_type = COALESCE(trigger_source_type, 'writeback') WHERE prompt_key = 'finance_plan_followup' AND scene_description IS NULL;
UPDATE return_visit_prompts SET scene_description = '沉默客户唤醒：客户长时间未回复，以库存/福利/检测报告为切入点轻提醒。', trigger_source_type = COALESCE(trigger_source_type, 'writeback') WHERE prompt_key = 'silent_customer_wakeup' AND scene_description IS NULL;

CREATE TABLE return_visit_followup_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_visit_run_id INTEGER NOT NULL,
    lead_id INTEGER,
    staff_id INTEGER,
    prompt_key VARCHAR(64),
    sla_minutes INTEGER,
    deadline DATETIME,
    actual_followup_at DATETIME,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    wechat_task_id INTEGER,
    created_at DATETIME,
    updated_at DATETIME
);
CREATE INDEX idx_return_visit_followup_tasks_run ON return_visit_followup_tasks(return_visit_run_id);
CREATE INDEX idx_return_visit_followup_tasks_status ON return_visit_followup_tasks(status);
