-- 0006 抖音 OpenAPI 图片上传记录
-- 范围：只记录 /upload_image_file 上传尝试和上游返回的图片元数据。
-- 禁止保存原始图片二进制或完整 image_base64。

CREATE TABLE IF NOT EXISTS douyin_image_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    main_account_id INTEGER NOT NULL,
    open_id VARCHAR(255),
    file_name VARCHAR(255) NOT NULL,
    file_ext VARCHAR(16) NOT NULL,
    mime_type VARCHAR(64) NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    local_md5 VARCHAR(64) NOT NULL,
    image_base64_sha256 VARCHAR(64) NOT NULL,
    upstream_image_id VARCHAR(255),
    upstream_width INTEGER,
    upstream_height INTEGER,
    upstream_md5 VARCHAR(255),
    upload_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    upstream_code VARCHAR(64),
    upstream_msg VARCHAR(500),
    request_body_json TEXT,
    response_body_json TEXT,
    error_message VARCHAR(500),
    created_at DATETIME,
    updated_at DATETIME,
    uploaded_at DATETIME
);
