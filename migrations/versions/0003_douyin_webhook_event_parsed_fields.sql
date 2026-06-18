-- 0003 Douyin callback parsed private-message fields
-- Scope: keep raw webhook events and add normalized fields for later send_msg context.

ALTER TABLE douyin_webhook_events ADD COLUMN client_key VARCHAR(255);
ALTER TABLE douyin_webhook_events ADD COLUMN conversation_short_id VARCHAR(255);
ALTER TABLE douyin_webhook_events ADD COLUMN server_message_id VARCHAR(255);
ALTER TABLE douyin_webhook_events ADD COLUMN conversation_type VARCHAR(32);
ALTER TABLE douyin_webhook_events ADD COLUMN message_type VARCHAR(64);
ALTER TABLE douyin_webhook_events ADD COLUMN message_create_time DATETIME;
ALTER TABLE douyin_webhook_events ADD COLUMN message_source VARCHAR(128);
ALTER TABLE douyin_webhook_events ADD COLUMN from_user_nick_name VARCHAR(255);
ALTER TABLE douyin_webhook_events ADD COLUMN from_user_avatar VARCHAR(1000);
ALTER TABLE douyin_webhook_events ADD COLUMN to_user_nick_name VARCHAR(255);
ALTER TABLE douyin_webhook_events ADD COLUMN to_user_avatar VARCHAR(1000);
ALTER TABLE douyin_webhook_events ADD COLUMN parse_status VARCHAR(32);
ALTER TABLE douyin_webhook_events ADD COLUMN parse_error VARCHAR(255);
ALTER TABLE douyin_webhook_events ADD COLUMN parsed_content_json TEXT;
