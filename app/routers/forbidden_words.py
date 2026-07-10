"""违禁词超管管理 API。

复用既有权限码 auto_wechat:admin:forbidden_words，不新增权限码。
一期为全局词库，管理接口只做词库只读 + 词条 CRUD + 启停；
命中日志查询不在本阶段提供，测试直接查数据库验证。
所有写接口对 word/safe_word 做 strip，拒绝空 safe_word，拒绝同库大小写等价重复词。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.models import ForbiddenWord, ForbiddenWordLibrary


router = APIRouter(prefix="/admin", tags=["管理员-违禁词管理"])


class ForbiddenWordCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    library_key: str = Field(..., min_length=1, max_length=64)
    word: str = Field(..., min_length=1, max_length=100)
    safe_word: str = Field(..., min_length=1, max_length=100)
    severity: str | None = Field(None, max_length=32)
    enabled: bool = True


class ForbiddenWordUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    word: str | None = Field(None, min_length=1, max_length=100)
    safe_word: str | None = Field(None, min_length=1, max_length=100)
    severity: str | None = Field(None, max_length=32)
    enabled: bool | None = None


class ForbiddenWordToggleRequest(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool


def _require_admin(context: RequestContext) -> RequestContext:
    if not context.has_permission("auto_wechat:admin:forbidden_words"):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少权限 auto_wechat:admin:forbidden_words"},
        )
    return context


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


def _ok(data: dict) -> dict:
    return {"success": True, "data": data, "message": "success"}


def _library_response(lib: ForbiddenWordLibrary) -> dict:
    return {
        "id": lib.id,
        "library_key": lib.library_key,
        "name": lib.name,
        "description": lib.description,
        "scope": lib.scope,
        "enabled": bool(lib.enabled),
        "sort_order": lib.sort_order,
    }


def _word_response(word: ForbiddenWord, library_key: str | None) -> dict:
    return {
        "id": word.id,
        "library_id": word.library_id,
        "library_key": library_key,
        "word": word.word,
        "safe_word": word.safe_word,
        "severity": word.severity,
        "enabled": bool(word.enabled),
        "hit_count": word.hit_count,
    }


def _library_by_key(db: Session, library_key: str) -> ForbiddenWordLibrary | None:
    return (
        db.query(ForbiddenWordLibrary)
        .filter(ForbiddenWordLibrary.library_key == library_key)
        .first()
    )


def _has_casefold_duplicate(db: Session, library_id: int, word: str, exclude_id: int | None = None) -> bool:
    """同一词库下大小写等价重复检测。"""
    query = db.query(ForbiddenWord).filter(ForbiddenWord.library_id == library_id)
    if exclude_id is not None:
        query = query.filter(ForbiddenWord.id != exclude_id)
    target = word.casefold()
    return any((row.word or "").casefold() == target for row in query.all())


def _validate_word_required(value: str) -> str:
    """strip 后拒绝纯空白 word；纯空格能绕过 Pydantic min_length（按字符数计）。"""
    word = value.strip()
    if not word:
        raise _bad_request("WORD_REQUIRED", "违禁词不能为空")
    return word


@router.get("/forbidden-word-libraries")
def list_libraries(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """列出全部违禁词库（全局配置，一期固定 3 类 seed + 超管后续扩展）。"""
    _require_admin(context)
    libs = (
        db.query(ForbiddenWordLibrary)
        .order_by(ForbiddenWordLibrary.sort_order, ForbiddenWordLibrary.id)
        .all()
    )
    return _ok({"total": len(libs), "items": [_library_response(lib) for lib in libs]})


@router.get("/forbidden-words")
def list_words(
    library_key: str | None = None,
    enabled: bool | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """按词库 / 启停 / 关键字过滤词条，返回脱敏展示字段。"""
    _require_admin(context)
    query = (
        db.query(ForbiddenWord, ForbiddenWordLibrary)
        .join(ForbiddenWordLibrary, ForbiddenWord.library_id == ForbiddenWordLibrary.id)
    )
    if library_key:
        query = query.filter(ForbiddenWordLibrary.library_key == library_key)
    if enabled is not None:
        query = query.filter(ForbiddenWord.enabled.is_(enabled))
    if keyword:
        escaped = keyword.replace("%", "\\%").replace("_", "\\_")
        query = query.filter(ForbiddenWord.word.like(f"%{escaped}%", escape="\\"))
    rows = query.order_by(ForbiddenWord.id.desc()).all()
    items = [_word_response(word, lib.library_key) for word, lib in rows]
    return _ok({"total": len(items), "items": items})


@router.post("/forbidden-words")
def create_word(
    payload: ForbiddenWordCreateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """新增词条；校验词库存在、safe_word 非空、同库大小写等价查重。"""
    _require_admin(context)
    word = _validate_word_required(payload.word)
    safe_word = payload.safe_word.strip()
    if not safe_word:
        raise _bad_request("SAFE_WORD_REQUIRED", "安全替换词不能为空")
    library = _library_by_key(db, payload.library_key)
    if library is None:
        raise _not_found("LIBRARY_NOT_FOUND", "违禁词库不存在")
    if _has_casefold_duplicate(db, library.id, word):
        raise _bad_request("WORD_DUPLICATED", "同一词库已存在相同违禁词")
    record = ForbiddenWord(
        library_id=library.id,
        word=word,
        safe_word=safe_word,
        severity=payload.severity,
        enabled=payload.enabled,
        hit_count=0,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _ok(_word_response(record, library.library_key))


@router.put("/forbidden-words/{word_id}")
def update_word(
    word_id: int,
    payload: ForbiddenWordUpdateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """更新词条字段；word 变更需重新查重，safe_word 不得置空。"""
    _require_admin(context)
    record = db.get(ForbiddenWord, word_id)
    if record is None:
        raise _not_found("WORD_NOT_FOUND", "违禁词不存在")
    library = db.get(ForbiddenWordLibrary, record.library_id)
    data = payload.model_dump(exclude_unset=True)

    if "word" in data and data["word"] is not None:
        new_word = _validate_word_required(data["word"])
        if new_word != record.word:
            if _has_casefold_duplicate(db, record.library_id, new_word, exclude_id=record.id):
                raise _bad_request("WORD_DUPLICATED", "同一词库已存在相同违禁词")
            record.word = new_word
    if "safe_word" in data and data["safe_word"] is not None:
        new_safe = data["safe_word"].strip()
        if not new_safe:
            raise _bad_request("SAFE_WORD_REQUIRED", "安全替换词不能为空")
        record.safe_word = new_safe
    if "severity" in data:
        record.severity = data["severity"]
    if "enabled" in data and data["enabled"] is not None:
        record.enabled = data["enabled"]

    db.commit()
    db.refresh(record)
    return _ok(_word_response(record, library.library_key if library else None))


@router.post("/forbidden-words/{word_id}/toggle")
def toggle_word(
    word_id: int,
    payload: ForbiddenWordToggleRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """启用/禁用词条；幂等，不触发发送。"""
    _require_admin(context)
    record = db.get(ForbiddenWord, word_id)
    if record is None:
        raise _not_found("WORD_NOT_FOUND", "违禁词不存在")
    record.enabled = payload.enabled
    db.commit()
    db.refresh(record)
    library = db.get(ForbiddenWordLibrary, record.library_id)
    return _ok(_word_response(record, library.library_key if library else None))
