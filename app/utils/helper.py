"""Response helpers for consistent API envelopes."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Mapping


def _load_catalog(filename: str) -> dict[str, dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "data" / filename
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        return {str(k): v for k, v in payload.items() if isinstance(v, dict)}
    return {}


class ResponseHelper:
    """Builds standardised API response envelopes from JSON detail catalogs."""

    _success = _load_catalog("success_detail.json")
    _error = _load_catalog("error_detail.json")
    _status_map: dict[int, str] = {
        400: "bad_request_error",
        401: "unauthorized_error",
        403: "forbidden_error",
        404: "not_found_error",
        409: "conflict_error",
        422: "validation_error",
        500: "server_error",
    }

    @classmethod
    def _build(
        cls,
        *,
        catalog: Mapping[str, Mapping[str, Any]],
        key: str | None,
        detail_type: str,
        msg: str,
        reason: str | None,
        data: Any,
        pagination: Mapping[str, Any] | None = None,
    ) -> dict:
        entry = catalog.get(key, {}) if key else {}
        resolved_type = entry.get("detail_type", detail_type)
        resolved_msg = entry.get("msg", msg)
        resolved_reason = reason if reason is not None else entry.get("reason")
        payload: dict[str, Any] = {
            "detail_type": resolved_type,
            "traceback_id": str(uuid.uuid4()),
            "msg": resolved_msg,
            "data": data if data is not None else {},
        }
        if resolved_reason is not None:
            payload["ctx"] = {"reason": resolved_reason}
        response: dict[str, Any] = {"detail": [payload]}
        if pagination is not None:
            response["pagination"] = dict(pagination)
        return response

    @classmethod
    def success(
        cls,
        data: Any = None,
        msg: str = "Success",
        *,
        key: str | None = None,
        reason: str | None = None,
        detail_type: str = "Success",
        pagination: Mapping[str, Any] | None = None,
    ) -> dict:
        return cls._build(
            catalog=cls._success,
            key=key,
            detail_type=detail_type,
            msg=msg,
            reason=reason,
            data=data,
            pagination=pagination,
        )

    @classmethod
    def error(
        cls,
        msg: str = "Error",
        data: Any = None,
        *,
        key: str | None = None,
        reason: str | None = None,
        detail_type: str = "Error",
    ) -> dict:
        return cls._build(
            catalog=cls._error,
            key=key,
            detail_type=detail_type,
            msg=msg,
            reason=reason,
            data=data,
        )

    @classmethod
    def error_key_for_status(cls, status_code: int) -> str | None:
        return cls._status_map.get(status_code)

    @staticmethod
    def extract_error_info(detail: Any) -> tuple[str | None, str]:
        if isinstance(detail, dict):
            key = detail.get("error_key") or detail.get("key")
            reason = detail.get("reason") or detail.get("detail") or str(detail)
            return key, str(reason)
        return None, str(detail)
