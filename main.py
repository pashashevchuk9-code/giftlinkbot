from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from config import ConfigError, Settings
from database import Database
from deals import DealService
from gifts import GiftService
from handlers import router
from instance_lock import InstanceLock
from middleware import AccessGateMiddleware
from nft import NFTResolver

logger = logging.getLogger(__name__)


class TokenRedactionFilter(logging.Filter):
    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            if self._token and self._token in message:
                record.msg = message.replace(self._token, "<redacted-token>")
                record.args = ()
        except Exception:
            pass
        return True


class RedactingFormatter(logging.Formatter):
    """Скрывает токен даже в traceback и тексте исключений."""

    def __init__(self, *args, token: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._token = token

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if self._token:
            text = text.replace(self._token, "<redacted-token>")
        return text


def setup_logging(
    level: str,
    token: str,
    log_path: Path | None = None,
) -> None:
    formatter = RedactingFormatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        token=token,
    )
    root = logging.getLogger()
    root.handlers.clear()

    # pythonw.exe (автозапуск без окна) не имеет sys.stdout.
    if sys.stdout is not None:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.addFilter(TokenRedactionFilter(token))
        root.addHandler(console)

    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=5_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(TokenRedactionFilter(token))
            root.addHandler(file_handler)
        except OSError as exc:
            if sys.stderr is not None:
                print(
                    f"Не удалось открыть лог-файл {log_path}: {exc}",
                    file=sys.stderr,
                )

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


async def expiration_worker(service: DealService) -> None:
    while True:
        try:
            await service.db.expire_maintenance()
            await service.expire_offers()
            await service.expire_payments()
            await service.refresh_pending_cards()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка в обработчике сроков")
        await asyncio.sleep(20)


async def heartbeat_worker(bot: Bot, db: Database) -> None:
    """Отправляет heartbeat-сообщение @HelpingGiftIinkBot каждые 5 минут.

    Это предотвращает засыпание сервиса и служит мониторингом.
    Если пользователь не запустил бота, heartbeat пропускается.
    """
    chat_id = None
    try:
        chat = await bot.get_chat("@HelpingGiftIinkBot")
        chat_id = chat.id
        logger.info("Heartbeat: resolved @HelpingGiftIinkBot -> %s", chat_id)
    except Exception as exc:
        logger.warning("Heartbeat: не удалось разрешить @HelpingGiftIinkBot: %s", exc)

    if chat_id is None:
        # Повторная попытка через 60 сек
        await asyncio.sleep(60)
        try:
            chat = await bot.get_chat("@HelpingGiftIinkBot")
            chat_id = chat.id
            logger.info("Heartbeat: resolved @HelpingGiftIinkBot -> %s", chat_id)
        except Exception as exc:
            logger.warning("Heartbeat: повторная попытка не удалась: %s", exc)
            return

    while True:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="💓 Heartbeat: бот работает. " + datetime.now().strftime("%H:%M:%S"),
                disable_notification=True,
            )
            logger.debug("Heartbeat sent to %s", chat_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Heartbeat: ошибка отправки: %s", exc)
        await asyncio.sleep(300)  # 5 минут


async def start_health_server() -> web.AppRunner | None:
    """Небольшой HTTP-сервер для Render и других хостингов с проверкой порта.

    Локально PORT не задан, поэтому сервер не запускается и поведение
    бота не меняется.
    """
    raw_port = os.getenv("PORT", "").strip()
    if not raw_port:
        return None
    try:
        port = int(raw_port)
    except ValueError:
        logger.warning("Некорректный PORT=%r, HTTP-сервер не запущен", raw_port)
        return None

    async def health(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "service": "giftlinkbot",
                "time": datetime.now().isoformat(timespec="seconds"),
            }
        )

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("HTTP health-сервер слушает порт %s", port)
    return runner


async def set_commands(bot: Bot, settings: Settings) -> None:
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="profile", description="Мой профиль"),
        BotCommand(command="deals", description="Мои предложения"),
        BotCommand(command="history", description="История сделок"),
        BotCommand(command="rules", description="Правила обмена"),
        BotCommand(command="comand", description="Список команд"),
        BotCommand(command="help", description="Как сделать предложение"),
        BotCommand(command="whoami", description="Мой Telegram ID"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception:
        logger.warning("Не удалось установить меню команд")

    if not settings.owner_ids:
        return
    owner_commands = commands + [
        BotCommand(command="roles", description="Выдать роль пользователю"),
        BotCommand(command="setrole", description="Назначить роль"),
        BotCommand(command="removerole", description="Снять роль"),
        BotCommand(command="admins", description="Список администраторов"),
        BotCommand(command="maintenance", description="Технический режим"),
        BotCommand(command="zakrit", description="Выключить на 12 часов"),
        BotCommand(command="open", description="Включить досрочно"),
        BotCommand(command="adminlog", description="Журнал действий"),
        BotCommand(command="backup", description="Резервная копия"),
    ]
    for owner_id in settings.owner_ids:
        try:
            await bot.set_my_commands(
                owner_commands,
                scope=BotCommandScopeChat(chat_id=owner_id),
            )
        except Exception:
            logger.debug(
                "Не удалось установить меню OWNER для %s", owner_id, exc_info=True
            )


def _write_startup_error(message: str) -> None:
    """Пишет ошибку до настройки logging, в том числе при запуске через pythonw."""
    try:
        log_dir = Path(__file__).resolve().parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (log_dir / "bot.log").open("a", encoding="utf-8") as log_file:
            log_file.write(f"{timestamp} | ERROR    | {message}\n")
    except OSError:
        pass

    if sys.stderr is not None:
        print(message, file=sys.stderr)


async def run() -> int:
    try:
        settings = Settings.load()
    except ConfigError as exc:
        _write_startup_error(f"Ошибка конфигурации: {exc}")
        return 2

    setup_logging(
        settings.log_level,
        settings.bot_token,
        Path(__file__).resolve().parent / "logs" / "bot.log",
    )

    instance_lock = InstanceLock(
        settings.bot_token,
        settings.database_path.parent / "bot.lock",
    )
    if not instance_lock.acquire():
        logger.error(
            "Бот уже запущен в другом процессе. Остановите его или удалите "
            "задачу автозапуска перед повторным стартом."
        )
        return 5

    if not settings.payments_available:
        logger.warning(
            "Оплата Stars отключена: нужны ADMIN_IDS, PAYMENTS_ENABLED=true "
            "и OPERATOR_PAYOUT_ACK=true. Приём Stars не будет запущен."
        )

    db = Database(settings.database_path)
    await db.init()
    await db.seed_env_roles(
        admin_ids=settings.admin_ids,
        owner_ids=settings.owner_ids,
    )
    if not settings.owner_ids:
        logger.warning(
            "OWNER_ID не задан в .env. Роль OWNER недоступна, управление "
            "ролями и техрежимом работать не будет."
        )

    session = aiohttp.ClientSession()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    expiry_task: asyncio.Task | None = None
    heartbeat_task: asyncio.Task | None = None
    health_runner: web.AppRunner | None = None

    try:
        health_runner = await start_health_server()
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            logger.error(
                "Telegram отклонил BOT_TOKEN. Проверьте токен в .env или отзовите "
                "старый и создайте новый через BotFather."
            )
            return 3
        except TelegramNetworkError as exc:
            logger.error("Нет связи с Telegram API: %s", exc)
            return 4

        logger.info("Подключение к Telegram проверено: @%s (id=%s)", me.username, me.id)
        if not me.can_join_groups:
            logger.warning("В BotFather бот не может вступать в группы.")

        nft = NFTResolver(session)
        gifts = GiftService(bot, db)
        service = DealService(
            bot=bot,
            db=db,
            settings=settings,
            nft=nft,
            gifts=gifts,
            bot_username=me.username or "bot",
        )

        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(router)
        dp.message.middleware(AccessGateMiddleware())
        dp.callback_query.middleware(AccessGateMiddleware())
        dp["db"] = db
        dp["settings"] = settings
        dp["service"] = service
        dp["nft"] = nft
        dp["gifts"] = gifts

        await set_commands(bot, settings)
        await service.expire_offers()
        await service.expire_payments()
        expiry_task = asyncio.create_task(expiration_worker(service), name="expiration-worker")
        heartbeat_task = asyncio.create_task(heartbeat_worker(bot, db), name="heartbeat-worker")

        logger.info("Бот запущен. Ожидание сообщений.")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        return 0
    except Exception:
        logger.exception("Критическая ошибка при работе бота")
        return 1
    finally:
        if expiry_task is not None:
            expiry_task.cancel()
            try:
                await expiry_task
            except asyncio.CancelledError:
                pass
        if health_runner is not None:
            try:
                await health_runner.cleanup()
            except Exception:
                logger.debug("Не удалось остановить HTTP-сервер", exc_info=True)
        try:
            await bot.session.close()
        except Exception:
            pass
        await session.close()
        await db.close()
        instance_lock.release()
        logger.info("Бот остановлен.")


def main() -> None:
    try:
        code = asyncio.run(run())
    except KeyboardInterrupt:
        code = 0
    raise SystemExit(code)


if __name__ == "__main__":
    main()
