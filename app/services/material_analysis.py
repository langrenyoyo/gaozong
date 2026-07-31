"""素材多模态分析：用方舟多模态模型判断视频是否含人声口播 + 转写/描述。

上传素材后异步调用（BackgroundTask），不阻断上传响应。
- 用方舟 Files API 上传视频 → Responses API 对视频提问
- 判断是否含人声 → 自动设 category（口播/高光）
- 转写口播内容或描述片段 → 写入 AiEditMaterialAnalysis
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def analyze_material_async(material_id: int, presigned_url: str) -> None:
    """异步分析素材（后台任务入口）：上传方舟 → 判断人声 + 转写 → 写库。

    失败不抛异常（后台任务），仅记日志 + 设 analysis_status=failed。
    """
    from app.database import SessionLocal
    from app.models import AiEditMaterial, AiEditMaterialAnalysis

    ark_api_key = os.getenv("ARK_API_KEY", "").strip()
    if not ark_api_key:
        logger.warning("material_analysis_skip reason=no_ark_api_key material_id=%s", material_id)
        _update_analysis_status(material_id, "failed", error="未配置 ARK_API_KEY")
        return

    db = SessionLocal()
    try:
        material = db.query(AiEditMaterial).filter(AiEditMaterial.id == material_id).first()
        if material is None:
            logger.warning("material_analysis_skip reason=material_not_found material_id=%s", material_id)
            return

        material.analysis_status = "analyzing"
        db.commit()

        # 调方舟多模态分析
        result = _analyze_via_ark(presigned_url, ark_api_key)
        if result is None:
            material.analysis_status = "failed"
            db.commit()
            logger.warning("material_analysis_failed material_id=%s reason=ark_analysis_error", material_id)
            return

        # 判断 category：有口播 → 口播，无 → 高光
        has_speech = result.get("has_speech", False)
        category = "口播" if has_speech else "高光"
        material.category = category

        # 写/更新 AiEditMaterialAnalysis
        analysis = (
            db.query(AiEditMaterialAnalysis)
            .filter(AiEditMaterialAnalysis.material_id == material_id)
            .first()
        )
        transcript = result.get("transcript", "")
        description = result.get("description", "")
        analysis_data = {
            "has_speech": has_speech,
            "transcript": transcript,
            "description": description,
        }
        if analysis is None:
            analysis = AiEditMaterialAnalysis(
                material_id=material_id,
                source_sha256=material.source_sha256,
                analysis_version="ark_v1",
                transcript_json=json.dumps(analysis_data, ensure_ascii=False),
            )
            db.add(analysis)
        else:
            analysis.transcript_json = json.dumps(analysis_data, ensure_ascii=False)
            analysis.analysis_version = "ark_v1"

        material.analysis_status = "analyzed"
        db.commit()

        # 算力上报：方舟多模态分析消耗 LLM token，归类 ai_edit
        _report_analysis_usage(
            db,
            merchant_id=material.merchant_id,
            prompt_tokens=result.get("_prompt_tokens"),
            completion_tokens=result.get("_completion_tokens"),
        )
        logger.info(
            "material_analysis_done material_id=%s category=%s has_speech=%s",
            material_id, category, has_speech,
        )
    except Exception as exc:  # noqa: BLE001 后台任务异常不向上抛
        db.rollback()
        try:
            material = db.query(AiEditMaterial).filter(AiEditMaterial.id == material_id).first()
            if material:
                material.analysis_status = "failed"
                db.commit()
        except Exception:
            pass
        logger.error("material_analysis_error material_id=%s error_type=%s", material_id, type(exc).__name__, exc_info=True)
    finally:
        db.close()


def _update_analysis_status(material_id: int, status: str, error: str = "") -> None:
    """更新素材分析状态（独立 Session，不依赖外层事务）。"""
    from app.database import SessionLocal
    from app.models import AiEditMaterial

    db = SessionLocal()
    try:
        material = db.query(AiEditMaterial).filter(AiEditMaterial.id == material_id).first()
        if material:
            material.analysis_status = status
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _analyze_via_ark(video_url: str, api_key: str) -> dict[str, Any] | None:
    """调方舟多模态模型分析视频：判断是否含人声 + 转写/描述。

    返回 {has_speech: bool, transcript: str, description: str}，失败返回 None。
    """
    try:
        from volcenginesdkarkruntime import Ark  # type: ignore
    except ImportError:
        logger.warning("material_analysis_skip reason=no_ark_sdk")
        return None

    try:
        client = Ark(api_key=api_key)

        # 上传视频到方舟 Files API
        file_obj = client.files.create(
            url=video_url,
            purpose="user_data",
        )
        # 等待预处理完成
        client.files.wait_for_processing(file_obj.id)

        # 对视频提问：判断人声 + 转写/描述
        prompt = (
            "请分析这个视频，返回 JSON 格式：\n"
            '{"has_speech": true/false, "transcript": "如果有口播，转写完整内容；如果没有口播，留空", '
            '"description": "如果没有口播，描述视频片段内容（如外观/内饰/行驶画面）；如果有口播，简要补充画面描述"}\n'
            "has_speech: 视频中是否有人说话/口播（有真人声音讲解）。"
            "transcript: 口播文字内容（无人声时留空）。"
            "description: 画面描述。"
        )

        response = client.responses.create(
            model=os.getenv("ARK_MODEL", "doubao-seed-2-0-pro-260215"),
            input=[
                {"type": "input_video", "file_id": file_obj.id},
                {"type": "input_text", "text": prompt},
            ],
        )

        # 解析模型输出
        raw_output = ""
        for item in response.output:
            if hasattr(item, "text"):
                raw_output += item.text
            elif isinstance(item, dict) and "text" in item:
                raw_output += item["text"]

        parsed = _parse_ark_output(raw_output)
        if parsed is not None:
            # 提取方舟返回的 token 用量（供算力上报）
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            parsed["_prompt_tokens"] = prompt_tokens
            parsed["_completion_tokens"] = completion_tokens
        return parsed
    except Exception as exc:
        logger.warning("material_analysis_ark_error error_type=%s: %s", type(exc).__name__, exc)
        return None


def _parse_ark_output(raw: str) -> dict[str, Any] | None:
    """解析方舟模型输出为 {has_speech, transcript, description}。"""
    # 尝试从 raw 提取 JSON
    try:
        # 直接解析
        data = json.loads(raw)
        return {
            "has_speech": bool(data.get("has_speech", False)),
            "transcript": str(data.get("transcript", "")),
            "description": str(data.get("description", "")),
        }
    except (json.JSONDecodeError, TypeError):
        pass

    # 尝试提取 JSON 代码块
    import re
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return {
                "has_speech": bool(data.get("has_speech", False)),
                "transcript": str(data.get("transcript", "")),
                "description": str(data.get("description", "")),
            }
        except (json.JSONDecodeError, TypeError):
            pass

    logger.warning("material_analysis_parse_failed raw=%s", raw[:200])
    return None


def _report_analysis_usage(
    db: Session,
    *,
    merchant_id: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> None:
    """素材分析成功后上报算力消耗（capability_key=ai_edit，归类 AI剪辑）。

    按 prompt+completion token 总和计费；方舟未返回 usage 时按估算（prompt 字符数÷2）。
    上报失败不阻断分析流程。
    """
    if not merchant_id:
        return
    # 优先用方舟返回的真实 token；缺失时估算
    pt = int(prompt_tokens) if prompt_tokens else 0
    ct = int(completion_tokens) if completion_tokens else 0
    total = pt + ct
    if total <= 0:
        # 估算：分析 prompt 约 200 字符 ÷ 2 = 100 token
        total = 100
    try:
        from app.services.compute_service import record_usage as _record_usage

        _record_usage(
            db,
            merchant_id,
            total,
            capability_key="ai_edit",
            source="llm",
            model=os.getenv("ARK_MODEL", "doubao-seed-2-0-pro-260215"),
            remark="AI剪辑素材分析（方舟多模态）",
            usage_measurement_method="provider_tokens" if (pt or ct) else "estimated_tokens",
            prompt_tokens=pt or None,
            completion_tokens=ct or None,
        )
    except Exception as exc:  # noqa: BLE001 算力上报失败不阻断
        logger.warning("material_analysis_usage_report_error merchant_id=%s error=%s", merchant_id, exc)
