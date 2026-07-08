from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.xg_douyin_ai_cs.rag import repository
from apps.xg_douyin_ai_cs.rag.database import connect
from apps.xg_douyin_ai_cs.services.knowledge_training_service import _feedback_document_content


BAD_STANDARD_ANSWER_LABELS = ("有用", "一般", "不准")


def _metadata(value: str | None) -> dict:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_bad_feedback_content(content: str) -> bool:
    text = str(content or "")
    return "【标准回答】" in text and any(f"【标准回答】\n{label}" in text for label in BAD_STANDARD_ANSWER_LABELS)


def collect_repairs() -> list[dict]:
    repairs: list[dict] = []
    with connect() as conn:
        documents = conn.execute(
            """
            SELECT id, tenant_id, merchant_id, content, metadata_json
            FROM knowledge_documents
            WHERE source_type='douyin_cs_training_feedback' AND is_active=1
            ORDER BY id ASC
            """
        ).fetchall()
        for document in documents:
            if not _is_bad_feedback_content(document["content"]):
                continue
            metadata = _metadata(document["metadata_json"])
            training_id = str(metadata.get("training_id") or "").strip()
            if not training_id:
                repairs.append(
                    {
                        "document_id": int(document["id"]),
                        "status": "skipped",
                        "reason": "missing_training_id",
                    }
                )
                continue
            session = conn.execute(
                "SELECT question, answer FROM knowledge_training_sessions WHERE training_id=?",
                (training_id,),
            ).fetchone()
            feedback = conn.execute(
                """
                SELECT rating, comment, corrected_answer
                FROM knowledge_training_feedbacks
                WHERE training_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (training_id,),
            ).fetchone()
            if session is None or feedback is None:
                repairs.append(
                    {
                        "document_id": int(document["id"]),
                        "status": "skipped",
                        "reason": "missing_session_or_feedback",
                    }
                )
                continue
            new_content = _feedback_document_content(
                question=session["question"],
                original_answer=session["answer"],
                rating=feedback["rating"],
                comment=feedback["comment"],
                corrected_answer=feedback["corrected_answer"],
            )
            repairs.append(
                {
                    "document_id": int(document["id"]),
                    "tenant_id": document["tenant_id"],
                    "merchant_id": document["merchant_id"],
                    "status": "ready",
                    "content": new_content,
                }
            )
    return repairs


def _public_report(repairs: list[dict]) -> list[dict]:
    return [{key: value for key, value in item.items() if key != "content"} for item in repairs]


def apply_repairs(repairs: list[dict]) -> list[dict]:
    ready_repairs = [item for item in repairs if item.get("status") == "ready"]
    if not ready_repairs:
        return repairs

    with connect() as conn:
        for item in ready_repairs:
            conn.execute(
                """
                UPDATE knowledge_documents
                SET content=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (item["content"], item["document_id"]),
            )
        conn.commit()

    for item in ready_repairs:
        training = repository.train_document(
            tenant_id=item["tenant_id"],
            merchant_id=item["merchant_id"],
            document_id=int(item["document_id"]),
        )
        item["training_run_id"] = "" if not training else str(training.get("training_run_id") or "")
    return repairs


def main() -> None:
    parser = argparse.ArgumentParser(description="修复历史 AI 抖音客服训练反馈文档格式")
    parser.add_argument("--apply", action="store_true", help="实际更新文档并重训；默认只 dry-run")
    args = parser.parse_args()

    repairs = collect_repairs()
    if args.apply:
        repairs = apply_repairs(repairs)
    print(json.dumps(_public_report(repairs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
