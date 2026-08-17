# LAS speech_auto 请求代码与测试记录（2026-08-03）

> **冻结快照 / 历史追溯用，非当前事实**
> 本记录基于旧 `speech_auto` 单模式。2026-08-17 M06 三模式升级（M06-LAS-REMIX-MODES-20260817-1）后，
> 当前事实为 `marketing_headtalk / long_real_shot / real_shot_headtalk` 三模式，`speech_auto` 仅作兼容别名
> 规范化到 `marketing_headtalk`，`automotive_headtalk` 规范化到 `automotive`。当前接口合同见
> `docs/ai/13_ai_edit/contracts/LAS视频混剪_las_video_remix_接口调用说明_for小高.pdf`。
> 本快照仅保留 Shot.Empty 服务端故障排查历史（U-008）的追溯价值。

> 提供给 LAS 上游排查 `Shot.Empty: 初始化未产出分镜` / `Parameter.Invalid: 无法识别时长` 问题。

---

## 一、提交任务的请求代码

### 1.1 submit 请求结构

**端点**：`POST https://operator.las.cn-beijing.volces.com/api/v1/submit`

**鉴权**：HTTP Header `Authorization: Bearer ${LAS_API_KEY}`

**请求 body**：

```python
body = {
    "operator_id": "las_video_remix",
    "operator_version": "v1",
    "idempotent_id": idempotent_id,   # 每次唯一，幂等
    "data": {
        "video_urls": video_urls,      # 数组，元素为 URL 字符串
        "mode": "speech_auto",
        "template": "automotive_headtalk",
        "script": script,              # 自然语言创作指令
        "render_video": True,
    },
}
# 可选：output_tos_path 产物输出目录
if output_tos_path:
    body["data"]["output_tos_path"] = output_tos_path

resp = session.post(f"{base_url}/api/v1/submit", json=body, timeout=60)
```

### 1.2 `video_urls` 两种格式

我们测试了两种 `video_urls` 元素格式，**都失败**：

**格式 A：HTTPS 预签名 URL**（TOS SDK `generate_presigned_url` 生成）

```python
# 生成预签名 URL 的代码
import tos

auth = tos.Auth(access_key, secret_key, region)          # region=cn-guangzhou
client = tos.TosClient(auth, endpoint)                    # endpoint=https://tos-cn-guangzhou.volces.com

# 上传
client.put_object(Bucket=bucket, Key=key, Body=file_obj, ContentType="video/mp4")
# bucket=videoedit, key=las-speech-auto/third_client_006.mp4

# 生成预签名 https URL
url = client.generate_presigned_url(
    Method="GET",
    Bucket=bucket,         # videoedit
    Key=key,               # las-speech-auto/third_client_006.mp4
    ExpiresIn=604800,      # 7 天
)
# url 形如：
# https://videoedit.tos-cn-guangzhou.volces.com/las-speech-auto/third_client_006.mp4
#   ?X-Tos-Algorithm=TOS4-HMAC-SHA256
#   &X-Tos-Credential=AKLTZDBi.../20260803/cn-guangzhou/tos/request
#   &X-Tos-Date=20260803T053416Z
#   &X-Tos-Expires=604800
#   &X-Tos-SignedHeaders=host
#   &X-Tos-Signature=...
```

**格式 B：`tos://` 直传地址**

```python
# 直接构造 tos:// 地址（不经预签名）
video_urls = [f"tos://videoedit/las-speech-auto/{filename}" for filename in files]
# 形如：tos://videoedit/las-speech-auto/third_client_006.mp4
```

### 1.3 实际发送的请求体示例

**格式 A（HTTPS 预签名，task_id=7ffe776918d1e65621f0）**：

```json
{
  "operator_id": "las_video_remix",
  "operator_version": "v1",
  "idempotent_id": "speech-auto-xxxxxxxxxxxx",
  "data": {
    "video_urls": [
      "https://videoedit.tos-cn-guangzhou.volces.com/las-speech-auto/third_client_006.mp4?X-Tos-Algorithm=TOS4-HMAC-SHA256&X-Tos-Credential=AKLT***REDACTED***%2F20260803%2Fcn-guangzhou%2Ftos%2Frequest&X-Tos-Date=20260803T071242Z&X-Tos-Expires=604800&X-Tos-SignedHeaders=host&X-Tos-Signature=..."
    ],
    "mode": "speech_auto",
    "template": "automotive_headtalk",
    "script": "剪成一条约 60 秒的汽车真人讲解视频...",
    "render_video": true
  }
}
```

**格式 B（tos:// 直传，task_id=cf43403a72554106448c）**：

```json
{
  "operator_id": "las_video_remix",
  "operator_version": "v1",
  "idempotent_id": "speech-auto-xxxxxxxxxxxx",
  "data": {
    "video_urls": [
      "tos://videoedit/las-speech-auto/second_client_001.mp4",
      "tos://videoedit/las-speech-auto/second_client_002.mp4"
    ],
    "mode": "speech_auto",
    "template": "automotive_headtalk",
    "script": "将全部素材剪成一条约 45～60 秒的产品讲解视频...",
    "render_video": true
  }
}
```

---

## 二、测试矩阵

同一份素材（甲方 demo 原配视频，位于 `E:\work\project\auto_edit\samples\videos`），TOS bucket=`videoedit`，region=`cn-guangzhou`。

| # | `video_urls` 格式 | 素材 | 提交方式 | task_id | 结果 |
|---|---|---|---|---|---|
| 1 | HTTPS 预签名（7天有效） | 12 个 | demo 批量上传后提交 | `42265e26d467d24b0da2` | ❌ `Shot.Empty: 初始化未产出分镜` |
| 2 | `tos://` 直传 | 12 个 | 手动构造地址 | `cf43403a72554106448c` | ❌ `Parameter.Invalid: 仅支持时长可识别的视频` |
| 3 | `tos://` 直传 | third 7个 | 手动构造 | `4eed4bcf620fbb4097ee` | ❌ `Parameter.Invalid: 无法识别时长` |
| 4 | HTTPS 预签名（**现场临时生成，上传后立即提交**） | 1 个 | 零延迟 | `7ffe776918d1e65621f0` | ❌ `Shot.Empty: 初始化未产出分镜` |
| 对照 | HTTPS 预签名（**7月28日**） | 12 个 | demo 批量 | `61efd01182f3b3af92a4` | ✅ 成功（62.69s 成片，7 分镜） |

---

## 三、已排除的因素

1. **预签名 URL 过期**：测试 4 在 `2026-08-03 15:12:42` 生成 URL 并同一秒提交，`15:13:03` 失败，仅 21 秒，有效期 7 天，不可能过期。
2. **TOS 凭证失效**：TOS AK/SK 能正常列举 bucket `videoedit` 的对象，文件确实存在于 `las-speech-auto/` 前缀下。
3. **素材文件损坏**：MP4 的 `moov` atom 在文件开头（faststart 优化，`moov@32`），本地可解析时长；7月28日 LAS 也成功处理过同样的素材。
4. **请求代码错误**：7月28日用完全相同的 submit 代码和格式成功过（task_id `61efd01182f3b3af92a4`）。

---

## 四、请 LAS 侧排查

1. **task_id `7ffe776918d1e65621f0`（HTTPS 预签名，8月3日 15:12 失败）**：LAS 服务端实际从 TOS 拉取视频时，返回了什么？HTTP 200 拿到完整内容，还是 403/部分内容？这能区分"LAS 拉不到视频"还是"拉到了但算法处理失败"。
2. **对比 task_id `61efd01182f3b3af92a4`（7月28日成功）与 `7ffe776918d1e65621f0`（8月3日失败）**：两次都是 HTTPS 预签名、同一 bucket、同类素材，LAS 后台处理这两次的差异是什么？
3. **`automotive_headtalk` 模板或 `speech_auto` 模式是否在 7月29日-8月3日 有变更**？

---

## 五、关键配置参数

| 项 | 值 |
|---|---|
| LAS_BASE_URL | `https://operator.las.cn-beijing.volces.com` |
| operator_id | `las_video_remix` |
| operator_version | `v1` |
| template | `automotive_headtalk` |
| mode | `speech_auto` |
| TOS bucket | `videoedit` |
| TOS region | `cn-guangzhou` |
| TOS endpoint | `https://tos-cn-guangzhou.volces.com` |
| 预签名有效期 | 604800 秒（7天） |
| 预签名 Method | GET |
| 预签名 SignedHeaders | host |
