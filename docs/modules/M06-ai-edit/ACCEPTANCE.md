# M06 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| LAS client submit/poll/wait/parse | COVERED | test_las_client.py（4 用例） |
| process_las_job 轮询→终态→归档 | PARTIAL | test_ai_edit_result_delivery.py（32 用例，用 mock artifacts 非 mock LAS client.wait_for_terminal） |
| 临时 URL 不入 storage_key | COVERED | test_ai_edit_result_delivery.py:331,344 + test_independent_ai_edit_attack.py:711 |
| 标题三件套 | COVERED | test_ai_edit_result_delivery.py:251,259,425 |
| 视频标签 | COVERED | test_ai_edit_result_delivery.py:300,440,459 |
| 归档成功/失败→交付态 | COVERED | test_ai_edit_result_delivery.py:90,111,124,133,355,364 |
| 软删除四件套+幂等+TOS失败 | COVERED | test_ai_edit_result_delivery.py:207,219,229,241,404,518,555 |
| 越权（跨商户/无商户/已删/未归档） | COVERED | test_independent_ai_edit_attack.py（17 用例） |
| 下载 token fail-closed | COVERED | test_ai_edit_download_token.py（7 用例） |
| create_las_job 组装参数/submit/写库 | MISSING | 无直接测试 |
| 算力上报（_report_las_compute_usage） | MISSING | 无 LAS→compute 联动测试 |
| 端到端（真实 LAS submit→poll→archive） | MISSING | 全 mock 不触网 |

## E2E 验收清单（待 2-M06.2）

### DOCKER_TESTABLE
1. 创建 LAS job（mock LAS client submit）
2. 状态流转（mock poll → COMPLETED → 归档 → succeeded）
3. 软删除（mock TOS delete）
4. 下载 token 生成+验证
5. 跨商户隔离

### EXTERNAL_ENV_REQUIRED
6. 真实 LAS submit→poll→archive（需 LAS_API_KEY + TOS 凭证）
7. 算力上报真实记录（需 M07 compute 链路）

### NOT_APPLICABLE
8. Windows 19000 — M06 不依赖 Local Agent
9. 真实微信 — M06 不依赖微信
