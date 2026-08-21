"""违禁词统一检测/审计服务。

方案（G1-DELTA 后冻结）：移除"替换为安全词并继续发送"的替换语义，改为只检测/审计。
- 活跃词定义：词库 enabled 且 scope==global，词条 enabled，word 非空；safe_word 为兼容可选字段，
  不再作为活跃词过滤条件（safe_word 为空的词条仍进入 LLM 检查与检测）。
- 匹配：Python 标准库 re，多词按长度降序构建单个正则（长词优先），re.IGNORECASE，
  英文/中英混合按 casefold 等价；只检测不替换正文。
- 日志：同一调用按唯一词条写一行 ForbiddenWordHitLog，hit_count 按实际命中次数累计，
  摘要只保存脱敏摘要，不保存完整客户消息/LLM 响应/token/cookie/secret。
- 事务：服务内部只 flush，不 commit，保留调用方提交语义。
"""

from __future__ import annotations

import hashlib
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
    """违禁词检测返回结构（兼容旧调用方命名的只读结果）。

    changed 表示是否有命中；final_content 恒等于 original_content（不再替换正文）。
    """

    original_content: str
    final_content: str
    changed: bool
    hits: list[ForbiddenWordHit] = field(default_factory=list)
    audit_ids: list[int] = field(default_factory=list)

    @property
    def audit_id(self) -> int | None:
        return self.audit_ids[0] if self.audit_ids else None


_PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
# 微信/微信号/wx/wechat 后跟账号值统一脱敏为掩码值，不保留账号明文。
_WECHAT_ACCOUNT_PATTERN = re.compile(
    r"(微信号|微信|wx|wechat)\s*[A-Za-z0-9_\-]{3,}",
    flags=re.IGNORECASE,
)


def _normalize_context_id_for_log(raw: object) -> str:
    """forbidden_word_hit_logs.context_id（VARCHAR(64)）长度收敛，零 migration。

    超长（>64）时用"可读前缀 + SHA-256 截段"编码压缩到 64 内：仅审计路径降级，
    绝不因审计写入影响门禁判定与主链路（P0.5-DOUYIN-* 事故修复：context_id 曾为
    base64 conversation_short_id 72 字符 → StringDataRightTruncation → 事务回滚）。
    可观测：normalized 值落在列内；original_length / 完整 context_id_hash 落在 WARNING 日志。
    """
    raw_str = str(raw or "").strip()
    if len(raw_str) <= 64:
        return raw_str
    prefix = raw_str[:40]
    digest = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:23]
    normalized = f"{prefix}-{digest}"  # 40 + 1 + 23 = 64
    logger.warning(
        "forbidden_word_audit stage=context_id_truncated original_length=%d "
        "context_id_hash=%s context_id_prefix=%s（审计降级不阻断业务）",
        len(raw_str),
        hashlib.sha256(raw_str.encode("utf-8")).hexdigest(),
        prefix,
    )
    return normalized


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
    """加载全局启用的有效词条：词库 enabled 且 scope=global，词条 enabled 且 word 非空。

    safe_word 为兼容可选字段，不作为活跃词过滤条件（safe_word 为空的词条仍进入检测）。
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
        active.append((word, library))
    return active


def load_forbidden_words_for_llm(db: Session) -> list[str]:
    """加载全局启用的违禁词列表，供 9100 LLM 提示词注入与生成后确定性检查。

    第五节新语义：词库告诉 LLM 哪些词不能用，不在 9000 侧生成前替换。
    返回去重后的违禁词原文列表（不含 safe_word）。
    """
    active = _load_active_words(db)
    seen: set[str] = set()
    words: list[str] = []
    for word, _library in active:
        text = (word.word or "").strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            words.append(text)
    return words


def check_words_in_library(db: Session, *, library_key: str, content: str) -> list[str]:
    """按指定词库独立检测命中词（跨库同词不去重）。

    P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1：prohibited_auto_reply 与 finance_compliance
    等词库可能含相同词条（如"黑户"），check_forbidden_words 的跨库 casefold 去重会
    让同词只保留一个库的命中，导致本库命中丢失。pre-LLM 阻断必须按词库独立检测。
    """
    content_text = content if content is not None else ""
    if not content_text.strip():
        return []
    active = _load_active_words(db)
    words = [
        (word.word or "").strip()
        for word, lib in active
        if (lib.library_key or "") == library_key and (word.word or "").strip()
    ]
    if not words:
        return []
    ordered = sorted(set(words), key=lambda s: (-len(s), s))
    pattern = re.compile("|".join(re.escape(w) for w in ordered), flags=re.IGNORECASE)
    matched: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(content_text):
        word = match.group(0)
        if word.casefold() not in seen:
            seen.add(word.casefold())
            matched.append(word)
    return matched


def check_forbidden_words(
    db: Session,
    *,
    merchant_id: str,
    source: str,
    content: str,
    context: dict[str, object] | None = None,
) -> ForbiddenWordReplacementResult:
    """对内容做违禁词只检测/审计，不替换正文。

    命中时写 ForbiddenWordHitLog 并累计 hit_count，正文保持不变（final_content == original_content）。
    调用方自行决定是否阻断（如回访话术发送前检测、回访模板保存拒绝）。
    服务内部只 flush，由调用方最终 commit。
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

    # 只检测不替换：统计每个唯一词条在正文中的命中次数。
    counts: dict[str, int] = {}
    first_seen_order: list[str] = []
    for match in pattern.finditer(content_text):
        key = match.group(0).casefold()
        # casefold 等价可能落到同一键；正常情况键一定存在。
        if key not in casefold_index:
            continue
        counts[key] = counts.get(key, 0) + 1
        if key not in first_seen_order:
            first_seen_order.append(key)

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
    # 审计保护（Emergency Hotfix）：context_id 列 VARCHAR(64)，超长收敛（前缀+SHA 截段），
    # 只降级审计路径、不阻断业务；库内编码复用现有列，零 migration。
    context_id = _normalize_context_id_for_log(_ctx_str(ctx.get("context_id")))
    before_summary = summarize_replacement_text(content_text)
    after_summary = summarize_replacement_text(content_text)

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
        "forbidden_word_hit source=%s merchant_id=%s hit_kinds=%s total_hits=%s",
        source,
        merchant_id,
        len(hits),
        sum(h.count for h in hits),
    )

    return ForbiddenWordReplacementResult(
        original_content=content_text,
        final_content=content_text,
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
