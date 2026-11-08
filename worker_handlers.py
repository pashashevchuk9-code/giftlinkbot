"""Команды для роли WORKER."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from access import get_actor, require_message_permission, role_of
from config import Settings
from database import Database
from roles import Permission, Role

router = Router(name="worker")


@router.message(Command("workerpanel"))
async def cmd_workerpanel(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_PROFILE):
        return
    record = await get_actor(db, settings, message.from_user)
    if role_of(record) not in {Role.WORKER, Role.OWNER}:
        await message.reply("Команда доступна только сотрудникам FannyTeam.")
        return
    await message.reply(
        "<b>Панель сотрудника</b>\n\n"
        "Доступные команды:\n"
        "/workerinfo — информация о роли\n"
        "/workerstats — статистика сотрудника\n"
        "/workerhistory — история активности\n"
        "/workerhelp — помощь сотруднику"
    )


@router.message(Command("workerinfo"))
async def cmd_workerinfo(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_PROFILE):
        return
    record = await get_actor(db, settings, message.from_user)
    role = role_of(record)
    if role not in {Role.WORKER, Role.OWNER}:
        await message.reply("Команда доступна только сотрудникам FannyTeam.")
        return
    await message.reply(
        "<b>Информация о роли WORKER</b>\n\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"Роль: WORKER\n"
        f"Дата регистрации: {record.get('registered_at', '—')}\n"
        "Права: все возможности USER + панель сотрудника."
    )


@router.message(Command("workerstats"))
async def cmd_workerstats(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_PROFILE):
        return
    record = await get_actor(db, settings, message.from_user)
    if role_of(record) not in {Role.WORKER, Role.OWNER}:
        await message.reply("Команда доступна только сотрудникам FannyTeam.")
        return
    completed = await db.count_completed_deals(message.from_user.id)
    await message.reply(
        "<b>Статистика сотрудника</b>\n\n"
        f"Завершённые сделки: {completed}\n"
        "Предложений создано: см. /offers"
    )


@router.message(Command("workerhistory"))
async def cmd_workerhistory(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_HISTORY):
        return
    record = await get_actor(db, settings, message.from_user)
    if role_of(record) not in {Role.WORKER, Role.OWNER}:
        await message.reply("Команда доступна только сотрудникам FannyTeam.")
        return
    await message.reply(
        "<b>История активности</b>\n\n"
        "История активности сотрудника. Подробности в /history и /deals."
    )


@router.message(Command("workerhelp"))
async def cmd_workerhelp(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    await message.reply(
        "<b>Помощь сотруднику</b>\n\n"
        "/workerpanel — панель сотрудника\n"
        "/workerinfo — информация о роли\n"
        "/workerstats — статистика\n"
        "/workerhistory — история активности\n"
        "/start — главное меню\n"
        "/profile — профиль\n"
        "/offers — мои предложения\n"
        "/history — история сделок"
    )
