# M05 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| 素材 API/Service 合同（回收站互斥/同 SHA 收敛/跨商户并存/响应不泄露/平台只读） | COVERED | test_phase12_task12_material_api.py |
| 素材分析（人工覆盖优先/AI 快照不可变/表结构冻结） | COVERED | test_phase12_task12_material_analysis.py |
| 云端存储函数存在性 | PARTIAL | test_phase12_task12_material_cloud.py（合同占位测试，TOS 上传主链路未覆盖） |
| 素材 schema/约束（process 唯一/扩展列/purge 配对/同商户 SHA 唯一） | COVERED | test_phase12_task12_material_schema.py |
| TOS 上传端点（upload-tos 真实流程/probe/预签名刷新/复活软删） | MISSING | 无 |
| 方舟多模态分析（analyze_material_async 真实调用/失败态） | MISSING | 无 |
| 软删除引用拦截（被未终态 job 钉住 409） | MISSING | 无 |
| 删除端点 | MISSING | 无 |
| reanalyze 端点 | MISSING | 无 |
| Local Agent 注册端点 | MISSING | 无 |
| M06 素材消费（create_job 校验+pinned_sha256） | PARTIAL | 代码确认（ai_edit_service.py:241-280），无 E2E |
| 商户隔离 | COVERED | 合同测试覆盖跨商户并存/平台只读 |

## E2E 验收清单（待 2-M05.2）

### DOCKER_TESTABLE
1. 素材列表 + 分页
2. 上传素材（TOS 真实或 mock）
3. 软删除 + 引用拦截（409）
4. 重新分析
5. M06 create_job 校验素材 + pinned_sha256

### EXTERNAL_ENV_REQUIRED
6. TOS 真实上传（需 TOS_ACCESS_KEY/TOS_SECRET_KEY）
7. 方舟多模态分析（需 ARK API key）
8. LAS 预签名 URL 消费（需 LAS 环境，属 M06）

### NOT_APPLICABLE
9. Windows 19000 — M05 不依赖 Local Agent
10. 真实微信 — M05 不依赖微信
