from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .constants import (
    DEFAULT_OVERSHOOT_API_URL,
    OVERSHOOT_CHAT_COMPLETION_TIMEOUT_SECONDS,
)
from .fold_check import fold_check_stream_image_url
from .fold_check_prompts import (
    fold_check_completion_payload,
    fold_check_image_pair_completion_payload,
)
from .payload_utils import _parse_positive_int, _response_text

logger = logging.getLogger("uvicorn.error")

_CREATE_STREAM_RETRY_DELAYS = (1.0, 2.0, 4.0)
_CHAT_COMPLETION_RETRY_DELAYS = (0.5, 1.0, 2.0)
_KEEPALIVE_RETRY_DELAYS = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class OvershootStreamLease:
    stream_id: str
    publish_url: str
    publish_token: str
    ttl_seconds: int | None


@dataclass(frozen=True)
class OvershootKeepaliveResult:
    publish_url: str | None
    publish_token: str | None


@dataclass(frozen=True)
class OvershootStreamStatus:
    last_frame_at_ms: int | None
    state: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class OvershootCompletionResult:
    text: str
    completion_id: Any
    usage: Any
    cache: Any
    raw: dict[str, Any]


class OvershootClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_url: str = DEFAULT_OVERSHOOT_API_URL,
    ) -> None:
        self._model = model
        self._http = httpx.AsyncClient(
            base_url=api_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def create_stream(self) -> OvershootStreamLease:
        for attempt, delay in enumerate((0.0, *_CREATE_STREAM_RETRY_DELAYS), start=1):
            if delay:
                await asyncio.sleep(delay)
            response = await self._http.post("/streams")
            if response.is_success:
                data = _json_object(response, "Overshoot stream response")
                stream_id = _stream_id_from_response(data)
                publish_url, publish_token = _publish_details_from_response(data)
                ttl_seconds = _lease_ttl_seconds(data)
                if not stream_id or not publish_url or not publish_token:
                    if stream_id:
                        await self.close_stream(stream_id)
                    raise RuntimeError(
                        "Overshoot response missing stream id or publish info"
                    )
                return OvershootStreamLease(
                    stream_id=stream_id,
                    publish_url=publish_url,
                    publish_token=publish_token,
                    ttl_seconds=ttl_seconds,
                )
            if response.status_code == 503 and attempt <= len(
                _CREATE_STREAM_RETRY_DELAYS
            ):
                logger.warning(
                    "Overshoot stream create unavailable attempt=%s status=%s body=%s",
                    attempt,
                    response.status_code,
                    _response_text(response),
                )
                continue
            raise RuntimeError(
                "Failed to create Overshoot stream "
                f"(HTTP {response.status_code}): {_response_text(response)}"
            )
        raise RuntimeError("Failed to create Overshoot stream")

    async def close_stream(self, stream_id: str) -> None:
        try:
            response = await self._http.delete(f"/streams/{stream_id}")
        except httpx.HTTPError as error:
            logger.warning("stream=%s close failed error=%s", stream_id, error)
            return
        if not response.is_success and response.status_code != 404:
            logger.warning(
                "stream=%s close failed status=%s body=%s",
                stream_id,
                response.status_code,
                _response_text(response),
            )

    async def keepalive(self, stream_id: str) -> OvershootKeepaliveResult | None:
        for attempt, delay in enumerate((0.0, *_KEEPALIVE_RETRY_DELAYS), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await self._http.post(f"/streams/{stream_id}/keepalive")
            except httpx.HTTPError as error:
                logger.warning(
                    "stream=%s keepalive request failed attempt=%s error=%s",
                    stream_id,
                    attempt,
                    error,
                )
                continue
            if response.is_success:
                data = _json_object_or_empty(response)
                publish_url, publish_token = _publish_details_from_response(data)
                return OvershootKeepaliveResult(
                    publish_url=publish_url or None,
                    publish_token=publish_token or None,
                )
            retryable = response.status_code in {500, 502, 503, 504}
            logger.warning(
                "stream=%s keepalive failed attempt=%s status=%s body=%s",
                stream_id,
                attempt,
                response.status_code,
                _response_text(response),
            )
            if not retryable:
                return None
        return None

    async def stream_status(self, stream_id: str) -> OvershootStreamStatus | None:
        try:
            response = await self._http.get(f"/streams/{stream_id}")
        except httpx.HTTPError as error:
            logger.warning("stream=%s status poll failed error=%s", stream_id, error)
            return None
        if not response.is_success:
            logger.warning(
                "stream=%s status poll failed status=%s body=%s",
                stream_id,
                response.status_code,
                _response_text(response),
            )
            return None
        data = _json_object_or_empty(response)
        state = data.get("state")
        return OvershootStreamStatus(
            last_frame_at_ms=_parse_positive_int(data.get("last_frame_at_ms")),
            state=state if isinstance(state, str) else None,
            raw=data,
        )

    async def last_frame_at_ms(self, stream_id: str) -> int | None:
        status = await self.stream_status(stream_id)
        return None if status is None else status.last_frame_at_ms

    async def chat_completion(
        self,
        *,
        stream_id: str,
        session_id: str,
        prompt: str,
    ) -> OvershootCompletionResult | None:
        return await self.chat_completion_for_image(
            image_url=fold_check_stream_image_url(stream_id),
            thread_id=session_id,
            prompt=prompt,
            log_context=f"stream={stream_id}",
        )

    async def chat_completion_for_image(
        self,
        *,
        image_url: str,
        thread_id: str,
        prompt: str,
        log_context: str = "fold-check",
    ) -> OvershootCompletionResult | None:
        payload = fold_check_completion_payload(
            model=self._model,
            thread_id=thread_id,
            prompt=prompt,
            image_url=image_url,
        )
        return await self._chat_completion_with_payload(
            payload=payload,
            log_context=log_context,
        )

    async def chat_completion_for_image_pair(
        self,
        *,
        camera_image_url: str,
        reference_image_url: str,
        thread_id: str,
        prompt: str,
        log_context: str = "fold-check",
    ) -> OvershootCompletionResult | None:
        payload = fold_check_image_pair_completion_payload(
            model=self._model,
            thread_id=thread_id,
            prompt=prompt,
            camera_image_url=camera_image_url,
            reference_image_url=reference_image_url,
        )
        return await self._chat_completion_with_payload(
            payload=payload,
            log_context=log_context,
        )

    async def _chat_completion_with_payload(
        self,
        *,
        payload: dict[str, Any],
        log_context: str,
    ) -> OvershootCompletionResult | None:
        for attempt, delay in enumerate((0.0, *_CHAT_COMPLETION_RETRY_DELAYS), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await self._http.post(
                    "/chat/completions",
                    json=payload,
                    timeout=OVERSHOOT_CHAT_COMPLETION_TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as error:
                logger.warning(
                    "%s chat completion failed attempt=%s error=%s",
                    log_context,
                    attempt,
                    error,
                )
                continue
            if response.is_success:
                data = _json_object_or_empty(response)
                return OvershootCompletionResult(
                    text=_chat_completion_text(data),
                    completion_id=data.get("id"),
                    usage=data.get("usage"),
                    cache=_completion_cache_metadata(data),
                    raw=data,
                )
            if response.status_code in {401, 402, 403, 404}:
                raise RuntimeError(
                    "Overshoot chat completion failed "
                    f"(HTTP {response.status_code}): {_response_text(response)}"
                )
            retryable = response.status_code in {429, 500, 502, 503, 504}
            logger.warning(
                "%s chat completion failed attempt=%s status=%s body=%s",
                log_context,
                attempt,
                response.status_code,
                _response_text(response),
            )
            if not retryable:
                return None
        return None


def _json_object(response: httpx.Response, context: str) -> dict[str, Any]:
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"{context} was not an object")
    return data


def _json_object_or_empty(response: httpx.Response) -> dict[str, Any]:
    data = response.json()
    return data if isinstance(data, dict) else {}


def _stream_id_from_response(data: dict[str, Any]) -> str:
    return str(data.get("id") or data.get("stream_id") or "").strip()


def _publish_details_from_response(data: dict[str, Any]) -> tuple[str, str]:
    publish = data.get("publish")
    if not isinstance(publish, dict):
        publish = data.get("livekit")
    if not isinstance(publish, dict):
        publish = {}
    url = str(publish.get("url") or "").strip()
    token = str(
        publish.get("token")
        or publish.get("livekit_token")
        or data.get("livekit_token")
        or ""
    ).strip()
    return url, token


def _lease_ttl_seconds(data: dict[str, Any]) -> int | None:
    ttl_seconds = _parse_positive_int(data.get("ttl_seconds"))
    if ttl_seconds is not None:
        return ttl_seconds
    lease = data.get("lease")
    if not isinstance(lease, dict):
        return None
    return _parse_positive_int(lease.get("ttl_seconds"))


def _chat_completion_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    return ""


def _completion_cache_metadata(data: dict[str, Any]) -> Any:
    overshoot = data.get("overshoot")
    if not isinstance(overshoot, dict):
        return None
    return overshoot.get("cache")
