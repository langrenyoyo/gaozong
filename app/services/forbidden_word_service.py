"""违禁词统一替换服务。

一期规则：命中后替换为安全词并继续发送，不把命中作为拦截理由。
活跃词定义：词库 enabled 且 scope==global，词条 enabled，word 与 safe_word 均非空。
匹配：Python 标准库 re，多词按长度降序构建单个正则（长词优先），re.IGNORECASE，
英文/中英混合按 casefold 等价；单次替换不对安全词二次替换。
日志：同一调用按唯一词条写一行 ForbiddenWordHitLog，hit_count 按实际命中次数累计，
摘要只保存脱敏摘要，不保存完整客户消息/LLM 响应/token/cookie/secret。
事务：服务内部只 flush，不 commit，保留调用方提交语义。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import ForbiddenWord, ForbiddenWordHitLog, ForbiddenWordLibrary


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForbiddenWordHit:
    """单条违禁词命中结果。"""

    library_key: str
    word: str
    safe_word: str
    count: int


@dataclass(frozen=True)
class ForbiddenWordReplacementResult:
    """替换服务返回结构。"""

    original_content: str
    final_content: str
    changed: bool
    hits: list[ForbiddenWordHit] = field(default_factory=list)
    audit_ids: list[int] = field(default_factory=list)

    @property
    def audit_id(self) -> int | None:
        return self.audit_ids[0] if self.audit_ids else None


# 只允许从后端已校验上下文传入的字段；其它前端字段一律忽略。
_ALLOWED_CONTEXT_KEYS = (
    "context_type",
    "context_id",
    "conversation_short_id",
    "lead_id",
    "record_id",
    "task_id",
)

_PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
# 微信/微信号/wx/wechat 后跟账号值统一脱敏为掩码值，不保留账号明文。
_WECHAT_ACCOUNT_PATTERN = re.compile(
    r"(微信号|微信|wx|wechat)\s*[A-Za-z0-9_\-]{3,}",
    flags=re.IGNORECASE,
)


def summarize_replacement_text(text: object, *, max_len: int = 160) -> str:
    """对替换前/后文本生成脱敏摘要。

    1. 折叠连续空白为单个空格。
    2. 手机号前三后四脱敏。
    3. 微信/wx/wechat 后跟账号值统一替换为 微信号[masked]。
    4. 超长尾部追加 ...。
    """
    if text is None:
        return ""
    summary = re.sub(r"\s+", " ", str(text)).strip()

    summary = _PHONE_PATTERN.sub(
        lambda m: m.group(1)[:3] + "****" + m.group(1)[-4:],
        summary,
    )
    summary = _WECHAT_ACCOUNT_PATTERN.sub("微信号[masked]", summary)

    if len(summary) > max_len:
        summary = summary[:max_len] + "..."
    return summary


def _noop_result(content_text: str) -> ForbiddenWordReplacementResult:
    return ForbiddenWordReplacementResult(
        original_content=content_text,
        final_content=content_text,
        changed=False,
        hits=[],
        audit_ids=[],
    )


def _load_active_words(db: Session) -> list[tuple[ForbiddenWord, ForbiddenWordLibrary]]:
    """加载全局启用的有效词条：词库 enabled 且 scope=global，词条 enabled 且 word/safe_word 非空。

    过滤放 Python 层，避免 SQLite Boolean 列 filter 的类型歧义。
    """
    rows = (
        db.query(ForbiddenWord, ForbiddenWordLibrary)
        .join(ForbiddenWordLibrary, ForbiddenWord.library_id == ForbiddenWordLibrary.id)
        .all()
    )
    active: list[tuple[ForbiddenWord, ForbiddenWordLibrary]] = []
    for word, library in rows:
        if not bool(library.enabled):
            continue
        if (library.scope or "") != "global":
            continue
        if not bool(word.enabled):
            continue
        if not (word.word or "").strip():
            continue
        if not (word.safe_word or "").strip():
            continue
        active.append((word, library))
    return active


def replace_forbidden_words(
    db: Session,
    *,
    merchant_id: str,
    source: str,
    content: str,
    context: dict[str, object] | None = None,
) -> ForbiddenWordReplacementResult:
    """对内容做违禁词替换，写入命中日志并累计 hit_count。

    命中后替换为安全词并继续，不拦截。服务内部只 flush，由调用方最终 commit。
    """
    content_text = content if content is not None else ""

    # 空内容、空白内容：直接返回，不查询词库、不写日志。
    if not content_text.strip():
        return _noop_result(content_text)

    active = _load_active_words(db)
    if not active:
        return _noop_result(content_text)

    # 按违禁词长度降序构建正则，保证长词优先（现车很多 先于 现车）。
    # 同一 casefold 键只保留首个（排序后即最长），避免重复分支。
    ordered = sorted(active, key=lambda pair: len(pair[0].word or ""), reverse=True)
    casefold_index: dict[str, tuple[ForbiddenWord, ForbiddenWordLibrary]] = {}
    for word, library in ordered:
        key = (word.word or "").casefold()
        if not key:
            continue
        if key not in casefold_index:
            casefold_index[key] = (word, library)

    if not casefold_index:
        return _noop_result(content_text)

    # 正则分支按原始 word 长度降序排列，re 在每个位置按顺序尝试分支，长词优先命中。
    pattern_words = sorted(
        casefold_index.keys(),
        key=lambda k: len(casefold_index[k][0].word or ""),
        reverse=True,
    )
    pattern = re.compile(
        "|".join(re.escape(casefold_index[k][0].word) for k in pattern_words),
        flags=re.IGNORECASE,
    )

    counts: dict[str, int] = {}
    first_seen_order: list[str] = []

    def _replacer(match: re.Match[str]) -> str:
        key = match.group(0).casefold()
        # casefold 等价可能落到同一键；正常情况键一定存在。
        if key not in casefold_index:
            return match.group(0)
        counts[key] = counts.get(key, 0) + 1
        if key not in first_seen_order:
            first_seen_order.append(key)
        return casefold_index[key][0].safe_word

    final_content = pattern.sub(_replacer, content_text)

    if not counts:
        # 有活跃词但未命中任何：原文返回，不写日志。
        return _noop_result(content_text)

    # 构建命中结果（按首次出现顺序）。
    hits = [
        ForbiddenWordHit(
            library_key=casefold_index[key][1].library_key,
            word=casefold_index[key][0].word,
            safe_word=casefold_index[key][0].safe_word,
            count=counts[key],
        )
        for key in first_seen_order
    ]

    # 写命中日志（每唯一词条一行）+ 累计 hit_count；只 flush 不 commit。
    ctx = context or {}
    context_type = _ctx_str(ctx.get("context_type"))
    context_id = _ctx_str(ctx.get("context_id"))
    before_summary = summarize_replacement_text(content_text)
    after_summary = summarize_replacement_text(final_content)

    audit_ids: list[int] = []
    for hit in hits:
        log = ForbiddenWordHitLog(
            merchant_id=merchant_id,
            library_key=hit.library_key,
            word=hit.word,
            safe_word=hit.safe_word,
            source=source,
            context_type=context_type,
            context_id=context_id,
            before_text_summary=before_summary,
            after_text_summary=after_summary,
        )
        db.add(log)
        db.flush()
        audit_ids.append(log.id)

        word_obj = casefold_index[(hit.word or "").casefold()][0]
        word_obj.hit_count = (word_obj.hit_count or 0) + hit.count

    logger.info(
        "forbidden_word_replaced source=%s merchant_id=%s hit_kinds=%s total_hits=%s",
        source,
        merchant_id,
        len(hits),
        sum(h.count for h in hits),
    )

    return ForbiddenWordReplacementResult(
        original_content=content_text,
        final_content=final_content,
        changed=True,
        hits=hits,
        audit_ids=audit_ids,
    )


def _ctx_str(value: object) -> str | None:
    """从上下文取字符串字段，None 保留为 None，其它转 str。"""
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
