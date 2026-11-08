from pathlib import Path
p = Path("handlers.py")
s = p.read_text(encoding="utf-8")

# 1. Add asyncio import
if "import asyncio" not in s:
    s = s.replace("from __future__ import annotations\n", "from __future__ import annotations\n\nimport asyncio\n", 1)

# 2. Replace the inline query body: resolve NFT with short timeout, then create offer and answer
start = s.index("@router.inline_query()")
end = s.index("@router.chosen_inline_result()")
old_func = s[start:end]

new_func = '''@router.inline_query()
async def on_inline_query(
    inline_query: InlineQuery,
    db: Database,
    settings: Settings,
    service: DealService,
    nft: NFTResolver,
) -> None:
    try:
        if inline_query.from_user is None:
            return
        actor = await get_actor(db, settings, inline_query.from_user)
        role = role_of(actor)
        if role is Role.SKAM:
            await inline_query.answer([], cache_time=1, is_personal=True)
            return
        if not has_permission(role, Permission.CREATE_OFFER):
            await inline_query.answer([], cache_time=1, is_personal=True)
            return

        text = (inline_query.query or "").strip()
        parts = text.split()
        if not parts:
            await inline_query.answer(
                [],
                cache_time=1,
                is_personal=True,
                switch_pm_text="Введите: ссылка_на_NFT цена [ua|ru|en|ku]",
                switch_pm_parameter="inline",
            )
            return

        import re as _re

        language = await db.get_user_language(inline_query.from_user.id)
        if len(parts) >= 2 and parts[-1].lower() in {"ua", "ru", "en", "ku"}:
            language = parts[-1].lower()
            parts = parts[:-1]

        nft_url = None
        nft_slug = None
        amount_raw = None

        if parts[0].startswith("http") or "t.me/nft/" in parts[0].lower():
            nft_url = parts[0]
            nft_slug = parse_nft_link(nft_url)
            amount_raw = parts[1] if len(parts) > 1 else None
        elif len(parts) >= 3 and parts[-1].isdigit():
            amount_raw = parts[-1]
            name_part = " ".join(parts[:-1])
            num_match = _re.search(r"#?(\\d+)", name_part)
            if num_match:
                number = num_match.group(1)
                name = name_part.replace(num_match.group(0), "").strip().replace(" ", "")
                if name:
                    nft_slug = f"{name}-{number}"
                    nft_url = f"https://t.me/nft/{nft_slug}"
        elif len(parts) >= 2 and parts[-1].isdigit():
            amount_raw = parts[-1]
            nft_url = parts[0]
            nft_slug = parse_nft_link(nft_url)

        if nft_slug is None or amount_raw is None:
            await inline_query.answer(
                [],
                cache_time=1,
                is_personal=True,
                switch_pm_text="Формат: ссылка_на_NFT цена [ua|ru|en|ku]",
                switch_pm_parameter="inline",
            )
            return

        if not amount_raw.isdigit() or int(amount_raw) <= 0:
            await inline_query.answer(
                [],
                cache_time=1,
                is_personal=True,
                switch_pm_text="Цена должна быть числом больше нуля",
                switch_pm_parameter="inline",
            )
            return

        amount = int(amount_raw)

        min_stars = await service.effective_min_stars()
        max_stars = await service.effective_max_stars()
        if amount < min_stars or amount > max_stars:
            await inline_query.answer(
                [],
                cache_time=1,
                is_personal=True,
                switch_pm_text=f"Сумма: от {min_stars} до {max_stars} Stars",
                switch_pm_parameter="inline",
            )
            return

        # Быстрый заголовок из slug
        nft_title = nft_slug.replace("-", " ").replace("_", " ")
        num_match = _re.search(r"(\\d+)$", nft_slug)
        if num_match:
            name_part = nft_slug[:num_match.start()].replace("-", " ").replace("_", " ").strip()
            nft_title = f"{name_part} #{num_match.group(1)}" if name_part else nft_slug

        # Попытка разрешить NFT с коротким таймаутом (3 сек)
        nft_image_url = None
        nft_description = None
        nft_owner_label = None
        try:
            info = await asyncio.wait_for(nft.resolve(nft_url), timeout=3.0)
            if info:
                nft_title = info.title.strip()[:200] or nft_title
                nft_image_url = info.image_url
                nft_description = info.description
                nft_owner_label = info.owner_label
        except Exception as exc:
            logger.warning("NFT resolve failed/timed out for %s: %s", nft_slug, exc)

        now_ts = _now()
        expires_at = now_ts + settings.offer_ttl_seconds
        offer_id = await db.create_offer(
            group_chat_id=0,
            buyer_id=inline_query.from_user.id,
            buyer_username=inline_query.from_user.username,
            buyer_name=" ".join(
                p for p in (inline_query.from_user.first_name, inline_query.from_user.last_name) if p
            ),
            seller_id=None,
            seller_username=None,
            seller_name=None,
            nft_url=nft_url,
            nft_slug=nft_slug,
            nft_title=nft_title,
            nft_image_url=nft_image_url,
            nft_description=nft_description,
            nft_owner_label=nft_owner_label,
            amount=amount,
            expires_at=expires_at,
            language=language,
        )

        offer = await db.get_offer(offer_id)
        assert offer is not None
        card_text = service._caption(offer)
        keyboard = offer_main_keyboard(offer_id)

        if nft_image_url:
            result = InlineQueryResultPhoto(
                id=str(offer_id),
                photo_url=nft_image_url,
                thumbnail_url=nft_image_url,
                title=f"Предложить {amount} Stars за {nft_title}",
                description=card_text.replace("\\n", " ")[:200],
                caption=card_text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            result = InlineQueryResultArticle(
                id=str(offer_id),
                title=f"Предложить {amount} Stars за {nft_title}",
                description=card_text.replace("\\n", " ")[:200],
                input_message_content=InputTextMessageContent(
                    message_text=card_text,
                    parse_mode="HTML",
                    link_preview_options={"is_disabled": True},
                ),
                reply_markup=keyboard,
            )
        logger.info("Inline result created: offer_id=%s, has_photo=%s", offer_id, bool(nft_image_url))
        await inline_query.answer([result], cache_time=0, is_personal=True)

    except Exception as exc:
        logger.exception("Inline query error: %s", exc)
        try:
            await inline_query.answer([], cache_time=1, is_personal=True)
        except Exception:
            pass

'''

s = s[:start] + new_func + "\n" + s[end:]
p.write_text(s, encoding="utf-8")
print("done")
import ast
ast.parse(s)
print("SYNTAX OK")
