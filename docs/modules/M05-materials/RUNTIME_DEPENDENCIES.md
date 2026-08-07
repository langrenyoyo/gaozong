# M05 运行时依赖

> source_baseline: c26ec227e70d

## M05 → M06（两个层次）

### Business/data 层（M06 → M05 素材消费 CONTRACT）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M06→M05 | D | direct DB | create_job 校验素材 get_material_for_merchant + pinned_sha256 防漂移（ai_edit_service.py:256-269） |

> M06 消费 M05 素材是 **CONTRACT 依赖**（M06 → M05 方向），不是 M05 依赖 M06。

### Implementation 层（M05 ↔ M06 shared implementation coupling，另一维度）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M05↔M06 | S | shared code | 共用 ai_edit.py router + features/ai-edit/ 目录 + auto_wechat:ai_edit 权限（ai_edit.py:28, frontend routes.ts:6-7） |

> 解耦候选：拆分 router/feature 目录为 M05/materials 和 M06/editor，但当前共用不阻断功能。这是 Implementation Coupling 维度，与 Business/data 层分开描述。

## M05 → TOS（external，素材存储）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M05→TOS | X | TOS upload | TOSUploader.upload_and_presign（ai_edit.py:273-274, las_tos_uploader.py） |

## M05 → LAS（external，预签名 URL 喂给 M06 LAS）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M05→LAS | X | presigned URL | tos_presigned_url 写入 AiEditMaterial（models.py:1644），M06 LAS 消费 |

## M05 → M07（data，算力上报）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M05→M07 | D | service call | material_analysis.py:257 capability_key=ai_edit |

## M05 → 平台公共底座

| 底座 | 依赖方式 |
|---|---|
| auth/RBAC | auto_wechat:ai_edit（ai_edit.py:28-32） |
| 数据库 | 4 表 ORM（AiEditMaterial/Analysis/Process/Template）+ 1 共享表（AiEditJobMaterial） |

## Legacy / Compat

无。ai_edit 相关代码无 legacy/compat/deprecated 标记。与 LEGACY_REGISTER 无交叉引用。
