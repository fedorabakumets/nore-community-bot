from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections.abc import Mapping

import aiohttp
from aiogram.types import Message

from community_bot.aliases import is_command_message, parse_trigger
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import reputation_delta
from community_bot.nora import rule_intent, strip_address

logger = logging.getLogger(__name__)

_URL = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=3)
_QUOTA_KEY = "openrouter_attempts"
_DAY = 24 * 60 * 60
_DAILY_LIMIT = 45
_GLOBAL_INTERVAL = 5
_USER_INTERVAL = 30
_UNAVAILABLE = "Сейчас не получается ответить. Давай чуть позже."
_LIMIT_REACHED = "Меня засыпали вопросами. Давай чуть позже."
_PERSONA = (
    "Ты Нора, виртуальный персонаж закрытого сообщества из Петербурга. "
    "Пиши по-русски, на «ты», как собеседница в Telegram. Обычно хватит пары коротких фраз. "
    "Шути, иронизируй и можешь слегка подколоть. Иногда уместен мат. "
    "Избегай канцелярита, формальностей и длинных вступлений. "
    "Не выдумывай ничего об участниках, их данных, правилах и экономике сообщества или текущих событиях. "
    "Если таких сведений нет в сообщении, скажи, что не знаешь."
)


class OpenRouterChat:
    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._api_key = settings.openrouter_api_key
        self._model = settings.openrouter_model
        self._community_chat_id = settings.community_chat_id
        self._free_model = self._model == "openrouter/free" or bool(
            re.fullmatch(r"[\w.-]+/[\w.-]+:free", self._model, re.ASCII)
        )
        if not self._free_model:
            logger.warning("OPENROUTER_MODEL должна быть openrouter/free или моделью с суффиксом :free")
        self._busy = False
        self._next_request = 0.0
        self._next_user_request: dict[int, float] = {}
        self._blocked_until = 0.0

    def prompt_for(self, message: Message) -> str | None:
        if (
            (message.chat.type != "private" and message.chat.id != self._community_chat_id)
            or not message.from_user
            or message.from_user.is_bot
            or message.sender_chat
            or message.forward_origin
            or message.via_bot
        ):
            return None
        text = message.text or ""
        body = strip_address(text)
        if (
            not body or parse_trigger(text, include_disabled=True)
            or is_command_message(body, include_disabled=True)
            or reputation_delta(body) is not None or rule_intent(body) is not None
        ):
            return None
        return body

    async def _reserve_attempt(self) -> bool:
        now = time.time()
        async with self._db.connect() as db:
            # Commit before the HTTP call so failed attempts and restarts still count.
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute("SELECT value FROM bot_state WHERE key = ?", (_QUOTA_KEY,)) as cursor:
                row = await cursor.fetchone()
            recorded = json.loads(row["value"]) if row else []
            attempts = [stamp for stamp in recorded if stamp > now - _DAY]
            if len(attempts) >= _DAILY_LIMIT:
                return False
            attempts.append(now)
            await db.execute(
                "INSERT INTO bot_state(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_QUOTA_KEY, json.dumps(attempts)),
            )
            await db.commit()
            return True

    async def answer(self, prompt: str, user_id: int) -> str | None:
        now = time.monotonic()
        if (
            not self._api_key or not self._free_model or self._busy or now < self._blocked_until
            or now < self._next_request or now < self._next_user_request.get(user_id, 0)
        ):
            return None
        self._busy = True
        self._next_request = now + _GLOBAL_INTERVAL
        self._next_user_request = {uid: until for uid, until in self._next_user_request.items() if until > now}
        self._next_user_request[user_id] = now + _USER_INTERVAL
        try:
            if not await self._reserve_attempt():
                self._blocked_until = now + 60
                return None
            return await self._request(prompt)
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, sqlite3.Error):
            logger.warning("Не удалось получить ответ OpenRouter")
            return _UNAVAILABLE
        finally:
            self._busy = False

    async def _request(self, prompt: str) -> str:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session, session.post(
            _URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": _PERSONA},
                    {"role": "user", "content": prompt[:2000]},
                ],
                "max_completion_tokens": 400,
                "provider": {"max_price": {"prompt": 0, "completion": 0, "request": 0}},
            },
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                return self._handle_error(response.status, response.headers)
            payload = await response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict) and isinstance(error.get("code"), int):
                    return self._handle_error(error["code"], response.headers)
                choices = payload.get("choices")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    message = choices[0].get("message")
                    content = message.get("content") if isinstance(message, dict) else None
                    if isinstance(content, str) and content.strip():
                        text = content.strip()
                        return text if len(text) <= 700 else text[:699].rstrip() + "…"
        logger.warning("OpenRouter вернул пустой или некорректный ответ")
        return _UNAVAILABLE

    def _handle_error(self, status: int, headers: Mapping[str, str]) -> str:
        logger.warning("OpenRouter вернул ошибку %d", status)
        if status in {402, 429, 503}:
            retry_after = headers.get("Retry-After", "")
            delay = 3600 if status == 402 else 60
            if retry_after.isascii() and retry_after.isdecimal() and len(retry_after) <= 8:
                delay = max(delay, int(retry_after))
            reset = headers.get("X-RateLimit-Reset", "")
            if status == 429 and reset.isascii() and reset.isdecimal() and len(reset) <= 13:
                delay = max(delay, int(reset) / 1000 - time.time())
            self._blocked_until = time.monotonic() + delay
            return _LIMIT_REACHED if status == 429 else _UNAVAILABLE
        if status in {400, 401, 404}:
            self._blocked_until = time.monotonic() + 900
        elif status >= 500:
            self._blocked_until = time.monotonic() + 60
        return _UNAVAILABLE
