-- 0047 抖音汽车直播违禁词库 seed（来源：FORBIDDEN_WORDS_DOUYIN_LIVE_SOURCE.md 第4节）
-- 规则：排除单字符词条（含"最""V"）；qq/QQ casefold 去重；safe_word 全部 NULL；
-- 幂等：缺失词库才新增（scope=global），词条 WHERE NOT EXISTS 不覆盖已有运营状态。
-- 最终写入 403 条。

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'used_car_sales_base', '二手车销售基础违禁词', '二手车销售场景通用违禁词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'finance_compliance', '金融方案合规词库', '金融方案承诺相关合规词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'vehicle_condition_risk', '车况承诺风险词', '车况承诺相关风险词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'extreme_ad_words', '极限用语/绝对化用语', '直播极限用语与绝对化用语风险词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'state_sensitive_words', '涉政/权威/国家敏感词', '涉政权威国家敏感词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'inducement_fraud_words', '诱导/欺诈/限时消费词', '诱导欺诈限时消费风险词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'contact_guidance_words', '线下引流/联系方式引导词', '线下引流与联系方式引导词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'superstition_words', '迷信用语', '直播间迷信用语词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'superstition_words');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'incivility_words', '不文明/歧视用语', '不文明与歧视用语词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'incivility_words');

INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order)
SELECT 'ip_event_words', '版权/赛事/IP 词', '版权赛事IP风险词库', 'global', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words');

INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '故事车', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '故事车');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '事故车', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '事故车');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '瑕疵', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '瑕疵');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '改装', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '改装');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '报废', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '报废');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抵押车', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抵押车');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '换件', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '换件');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '过不了户', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '过不了户');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '收车', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '收车');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '回收', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '回收');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '二手车回收', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '二手车回收');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '加装', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '加装');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '升级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '升级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '改款', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '改款');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '车衣', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '车衣');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '贴膜', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '贴膜');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '车膜', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '车膜');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '车贴', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '车贴');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '轮毂', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '轮毂');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '购置税', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '购置税');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '购置税全免', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '购置税全免');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '卖车', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '卖车');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '分期', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '分期');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '贷款', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '贷款');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '置换', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '置换');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抵押', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抵押');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '征信', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '征信');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '按揭', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '按揭');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '黑户', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '黑户');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '金融', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '金融');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首付', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首付');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '利息', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '利息');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '利率', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '利率');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '免息', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '免息');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '0首付', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '0首付');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '免首付', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '免首付');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '投资回报', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '投资回报');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '众筹', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '众筹');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '千亿价值', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '千亿价值');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '价值洼地', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '价值洼地');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '价值天成', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '价值天成');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抄涨', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抄涨');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '炒股不如买房', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '炒股不如买房');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '纯天然', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '纯天然');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '祖传', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '祖传');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '特效', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '特效');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '无敌', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '无敌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '质量免检', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '质量免检');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '无需国家质量检测', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '无需国家质量检测');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '免抽检', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '免抽检');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '样板间实景图', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '样板间实景图');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '效果图', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '效果图');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最佳', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最佳');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最具', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最具');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最爱', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最爱');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最赚', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最赚');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最优', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最优');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最优秀', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最优秀');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最好', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最好');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最大', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最大');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最大程度', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最大程度');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最高', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最高');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最高级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最高级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最高档', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最高档');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最高端', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最高端');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最奢侈', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最奢侈');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最低', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最低');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最低级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最低级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最低价', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最低价');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最底', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最底');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最便宜', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最便宜');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '史上最低价', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '史上最低价');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '时尚最低价', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '时尚最低价');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最流行', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最流行');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最受欢迎', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最受欢迎');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最时尚', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最时尚');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最聚拢', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最聚拢');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最符合', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最符合');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最舒适', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最舒适');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最先', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最先');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最先进', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最先进');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最先进科学', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最先进科学');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最先进加工工艺', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最先进加工工艺');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最先享受', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最先享受');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最后', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最后');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最后一波', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最后一波');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最新', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最新');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最新科技', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最新科技');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最新科学', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最新科学');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '最新技术', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '最新技术');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '第一', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '第一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '中国第一', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '中国第一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全网第一', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全网第一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '销量第一', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '销量第一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '排名第一', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '排名第一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '唯一', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '唯一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '第一品牌', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '第一品牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, 'NO.1', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = 'NO.1');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, 'TOP1', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = 'TOP1');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '独一无二', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '独一无二');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全国第一', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全国第一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '一流', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '一流');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '一天', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '一天');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '仅此一次', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '仅此一次');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全国X大品牌之一', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全国X大品牌之一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '销冠', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '销冠');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国家级', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国家级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国际级', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国际级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全球级', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全球级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '宇宙级', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '宇宙级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '世界级', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '世界级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '千万级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '千万级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '百万级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '百万级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '星级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '星级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '甲级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '甲级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '超甲级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '超甲级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '顶级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '顶级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '顶尖', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '顶尖');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '尖端', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '尖端');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '顶级工艺', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '顶级工艺');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '顶级享受', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '顶级享受');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '高级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '高级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '极品', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '极品');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '极佳', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '极佳');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '绝佳', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '绝佳');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '终极', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '终极');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '极致', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '极致');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '致极', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '致极');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '极具', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '极具');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首个', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首个');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首选', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首选');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全球首发', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全球首发');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全国首家', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全国首家');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全网首发', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全网首发');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首款', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首款');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首家', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首家');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '独家', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '独家');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '独家配方', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '独家配方');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首发', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首发');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首席', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首席');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首府', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首府');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首屈一指', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首屈一指');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '首次', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '首次');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全国销量冠军', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全国销量冠军');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '填补国内空白', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '填补国内空白');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '独创', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '独创');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '开发者', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '开发者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '缔造者', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '缔造者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '创始者', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '创始者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '发明者', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '发明者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '绝对值', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '绝对值');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '绝对', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '绝对');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '大牌', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '大牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '精确', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '精确');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '超赚', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '超赚');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领导品牌', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领导品牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领先上市', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领先上市');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '巨星', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '巨星');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '著名', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '著名');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '奢侈', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '奢侈');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '世界领先', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '世界领先');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '遥遥领先', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '遥遥领先');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '金牌', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '金牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '名牌', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '名牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '优秀', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '优秀');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '王牌', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '王牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '销量冠军', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '销量冠军');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '永久', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '永久');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '掌门人', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '掌门人');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领袖品牌', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领袖品牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领袖', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领袖');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领导者', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领导者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '引领', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '引领');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '创领', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '创领');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领航', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领航');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '耀领', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '耀领');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '绝无仅有', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '绝无仅有');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '史无前例', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '史无前例');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '前无古人', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '前无古人');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '前无古人后无来者', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '前无古人后无来者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '万能', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '万能');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '百分之百', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '百分之百');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '100%', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '100%');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国际品质', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国际品质');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '高档', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '高档');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '正品', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '正品');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '至尊', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '至尊');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '至臻', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '至臻');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '臻品', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '臻品');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '臻致', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '臻致');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '臻席', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '臻席');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '压轴', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '压轴');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '问鼎', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '问鼎');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '空前', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '空前');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '绝后', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '绝后');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '绝版', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '绝版');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '无双', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '无双');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '非此莫属', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '非此莫属');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '前所未有', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '前所未有');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '无人能及', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '无人能及');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '鼎级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '鼎级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '鼎冠', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '鼎冠');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '定鼎', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '定鼎');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '翘楚之作', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '翘楚之作');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '不可再生', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '不可再生');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '无与伦比', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '无与伦比');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '卓越', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '卓越');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '卓著', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '卓著');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '完美', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '完美');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '淋漓尽致', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '淋漓尽致');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '珍稀', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '珍稀');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '臻稀', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '臻稀');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '稀少', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '稀少');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '稀世珍宝', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '稀世珍宝');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '千金难求', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '千金难求');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '世所罕见', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '世所罕见');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '不可多得', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '不可多得');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '空前绝后', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '空前绝后');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '屈指可数', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '屈指可数');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '冠军', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '冠军');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '王者', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '王者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '三甲', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '三甲');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '十强', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'extreme_ad_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '十强');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国家领导人', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国家领导人');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领导人', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领导人');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领导', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领导');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '行政机关', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '行政机关');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '政府机关', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '政府机关');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '处级干部', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '处级干部');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '警察', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '警察');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '交警', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '交警');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国徽', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国徽');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国旗', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国旗');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国歌', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国歌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '党徽', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '党徽');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国家领导人画像', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国家领导人画像');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '社会主义核心价值观', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '社会主义核心价值观');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '邪教', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '邪教');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '非法宗教', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '非法宗教');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '交通管制', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '交通管制');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '政策原因', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '政策原因');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '政务', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '政务');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '政府', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '政府');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国家免检', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国家免检');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '国家级产品', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '国家级产品');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '特供', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '特供');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '专供', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '专供');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '专家推荐', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '专家推荐');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '人民币图样', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '人民币图样');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '老字号', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '老字号');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '中国驰名商标', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '中国驰名商标');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '开门红', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '开门红');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '火热开抢', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '火热开抢');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '庆祝', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '庆祝');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '狂欢', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '狂欢');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '疫情', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '疫情');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '防疫补贴', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '防疫补贴');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抗疫英雄', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抗疫英雄');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '医护人员', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '医护人员');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '志愿者', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '志愿者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '社区工作者', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '社区工作者');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '网红', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '网红');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '明星', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '明星');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '行政用车', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '行政用车');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '处级领导用的', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'state_sensitive_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '处级领导用的');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '点击领奖', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '点击领奖');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '恭喜获奖', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '恭喜获奖');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全民免单', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全民免单');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '点击有惊喜', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '点击有惊喜');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '点击获取', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '点击获取');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '点击转身', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '点击转身');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '点击试穿', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '点击试穿');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '点击翻转', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '点击翻转');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '领取奖品', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '领取奖品');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '非转基因更安全', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '非转基因更安全');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '售罄', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '售罄');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '售空', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '售空');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '再不抢就没了', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '再不抢就没了');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '不会再便宜', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '不会再便宜');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '不会再便宜了', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '不会再便宜了');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '错过不再', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '错过不再');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '错过即无', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '错过即无');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '错过就没机会了', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '错过就没机会了');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '未曾有过的', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '未曾有过的');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '万人疯抢', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '万人疯抢');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '全民疯抢', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '全民疯抢');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抢疯了', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抢疯了');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抢购', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抢购');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抢爆', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抢爆');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '秒杀', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '秒杀');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '秒杀价', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '秒杀价');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '跳楼价', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '跳楼价');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '超大福利', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '超大福利');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '免费领', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '免费领');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '免费住', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '免费住');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '零距离', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '零距离');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '价格你来定', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '价格你来定');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抽奖', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抽奖');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '打赏', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '打赏');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '发红包', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '发红包');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '金钱', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '金钱');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '红包', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '红包');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '低价引流', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '低价引流');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '粉丝灯牌', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '粉丝灯牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '灯牌', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '灯牌');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '礼物', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '礼物');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '上飞机', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '上飞机');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '保时捷墨镜', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '保时捷墨镜');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '拍了', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '拍了');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '想要', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '想要');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '666', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '666');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '报名', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '报名');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '扣666', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '扣666');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '倒计时', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '倒计时');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '趁现在', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '趁现在');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '仅限', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '仅限');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '随时结束', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '随时结束');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '随时涨价', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '随时涨价');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '马上降价', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '马上降价');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '特惠趴', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '特惠趴');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '购物大趴', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '购物大趴');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '闪购', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '闪购');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '几天几夜', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '几天几夜');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '周年庆', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '周年庆');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '品牌团', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '品牌团');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '今天错过', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '今天错过');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '明天就没有这个优惠了', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'inducement_fraud_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '明天就没有这个优惠了');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '微信', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '微信');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '加微信', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '加微信');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '微信号', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '微信号');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '加我', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '加我');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '我加你', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '我加你');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '微信截图', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '微信截图');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '二维码', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '二维码');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '扫二维码', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '扫二维码');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '电话号码', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '电话号码');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '手机号', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '手机号');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '电话', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '电话');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '地址', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '地址');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '加主播', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '加主播');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '私信主播', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '私信主播');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '私下聊', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '私下聊');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '私下交易', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '私下交易');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '私下销售', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '私下销售');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '绕过平台', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '绕过平台');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, 'qq', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = 'qq');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '后台', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '后台');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '私域', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '私域');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '留联系方式', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '留联系方式');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '小红书', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '小红书');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '快手', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '快手');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '报价', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '报价');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '优惠', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'contact_guidance_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '优惠');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '招财', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '招财');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '好运', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '好运');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '算命', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '算命');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '招财进宝', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '招财进宝');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '健康富贵', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '健康富贵');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '提升运气', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '提升运气');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '有助事业', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '有助事业');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '护身', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '护身');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '平衡正负能量', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '平衡正负能量');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '消除精神压力', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '消除精神压力');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '调和气压', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '调和气压');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '逢凶化吉', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '逢凶化吉');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '时来运转', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '时来运转');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '万事亨通', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '万事亨通');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '旺人', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '旺人');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '旺财', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '旺财');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '助吉避凶', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '助吉避凶');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '转富招福', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'superstition_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '转富招福');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '黑鬼', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '黑鬼');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '尼哥', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '尼哥');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '杂种', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '杂种');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '东亚病夫', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '东亚病夫');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '小日本', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '小日本');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '大男子主义', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '大男子主义');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '普信男', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '普信男');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '单身狗', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '单身狗');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '瞎逼逼', NULL, 'critical', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '瞎逼逼');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '垃圾', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '垃圾');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '贵族', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '贵族');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '高贵', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '高贵');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '上流', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '上流');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '富人区', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '富人区');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '名门', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '名门');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '阶层', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '阶层');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '阶级', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '阶级');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '血腥', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '血腥');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '暴力', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '暴力');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '赌博', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '赌博');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '抽烟', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '抽烟');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '喝酒', NULL, 'low', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'incivility_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '喝酒');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '世界杯', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '世界杯');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '冬奥会', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '冬奥会');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '奥林匹克运动会', NULL, 'high', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '奥林匹克运动会');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '双十一', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '双十一');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '双十二', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '双十二');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '米老鼠', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '米老鼠');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '马里奥', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '马里奥');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '吉祥物', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '吉祥物');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, 'IP形象', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = 'IP形象');
INSERT INTO forbidden_words (library_id, word, safe_word, severity, enabled, hit_count)
SELECT id, '公众人物形象', NULL, 'medium', 1, 0 FROM forbidden_word_libraries WHERE library_key = 'ip_event_words'
AND NOT EXISTS (SELECT 1 FROM forbidden_words fw WHERE fw.library_id = forbidden_word_libraries.id AND fw.word = '公众人物形象');
