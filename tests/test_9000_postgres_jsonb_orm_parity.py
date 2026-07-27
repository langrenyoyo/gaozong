"""9000 PostgreSQL JSONB / ORM 一致性首批返修测试。"""

import json

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.models import (
    AiAutoReplyRun,
    AiReplyDecisionLog,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
    _JSONStringJSONB,
)


JSON_STRING_COLUMNS = (
    (AiAutoReplyRun, "gate_results_json"),
    (DouyinWebhookEvent, "raw_body"),
    (DouyinWebhookEvent, "parsed_content_json"),
    (DouyinPrivateMessageSend, "request_body_json"),
    (DouyinPrivateMessageSend, "response_body_json"),
    (AiReplyDecisionLog, "risk_flags_json"),
    (AiReplyDecisionLog, "tags_json"),
    (AiReplyDecisionLog, "rag_sources_json"),
    (AiReplyDecisionLog, "source_chunks_json"),
    (AiReplyDecisionLog, "allowed_category_keys_json"),
    (AiReplyDecisionLog, "raw_response_json"),
)


@pytest.mark.parametrize(("model", "column_name"), JSON_STRING_COLUMNS)
def test_j1_j2_shared_type_compiles_to_jsonb_and_text(model, column_name):
    column_type = model.__table__.c[column_name].type
    assert isinstance(column_type, _JSONStringJSONB)
    assert str(column_type.compile(dialect=postgresql.dialect())).upper() == "JSONB"
    assert str(column_type.compile(dialect=sqlite.dialect())).upper() == "TEXT"


def test_j3_shared_type_preserves_string_json_contract():
    column_type = _JSONStringJSONB()
    pg = postgresql.dialect()
    sq = sqlite.dialect()

    assert column_type.process_bind_param(None, pg) is None
    assert column_type.process_bind_param(None, sq) is None
    assert column_type.process_bind_param('{"a":1}', pg) == {"a": 1}
    assert column_type.process_bind_param('["x"]', pg) == ["x"]
    assert column_type.process_bind_param('"scalar"', pg) == "scalar"
    assert column_type.process_bind_param('{"a":1}', sq) == '{"a":1}'
    assert json.loads(column_type.process_result_value({"a": 1}, pg)) == {"a": 1}
    assert column_type.process_result_value('{"a":1}', sq) == '{"a":1}'

    with pytest.raises(json.JSONDecodeError):
        column_type.process_bind_param("{bad", pg)
