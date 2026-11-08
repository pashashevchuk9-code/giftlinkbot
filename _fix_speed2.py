from pathlib import Path
p = Path("handlers.py")
s = p.read_text(encoding="utf-8")

old = '''        try:
            info = await nft.resolve(nft_url)
        except Exception as exc:
            logger.warning("NFT resolve failed for %s: %s", nft_slug, exc)
            info = None
        nft_title = getattr(info, "title", None) or nft_slug
        nft_image_url = getattr(info, "image_url", None)
        nft_description = getattr(info, "description", None)
        nft_owner_label = getattr(info, "owner_label", None)

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
        logger.info("Inline result created: offer_id=%s", offer_id)
        await inline_query.answer([result], cache_time=0, is_personal=True)

        # Фоновое разрешение NFT (обновит карточку при выборе)
        async def _resolve_bg():
            try:
                info = await nft.resolve(nft_url)
                if info and info.image_url:
                    await db.conn.execute(
                        "UPDATE offers SET nft_title=?, nft_image_url=?, nft_description=?, nft_owner_label=? WHERE id=?",
                        (info.title.strip()[:200] or nft_slug, info.image_url, info.description, info.owner_label, offer_id),
                    )
                    await db.conn.commit()
                    logger.info("NFT resolved for offer %s: %s", offer_id, info.image_url)
            except Exception as exc:
                logger.warning("NFT resolve failed for %s: %s", nft_slug, exc)
        asyncio.ensure_future(_resolve_bg())'''

new = '''    # Быстрый заголовок из slug без сетевого запроса
    nft_title = nft_slug.replace("-", " ").replace("_", " ")
    import re as _re2
    num_match = _re2.search(r"(\\d+)$", nft_slug)
    if num_match:
        name_part = nft_slug[:num_match.start()].replace("-", " ").replace("_", " ").strip()
        nft_title = f"{name_part} #{num_match.group(1)}" if name_part else nft_slug

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
        nft_image_url=None,
        nft_description=None,
        nft_owner_label=None,
        amount=amount,
        expires_at=expires_at,
        language=language,
    )

    offer = await db.get_offer(offer_id)
    assert offer is not None
    card_text = service._caption(offer)
    keyboard = offer_main_keyboard(offer_id)

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
    logger.info("Inline result created: offer_id=%s", offer_id)
    await inline_query.answer([result], cache_time=0, is_personal=True)

    # Фоновое разрешение NFT (обновит карточку при выборе)
    async def _resolve_bg():
        try:
            info = await nft.resolve(nft_url)
            if info and info.image_url:
                await db.conn.execute(
                    "UPDATE offers SET nft_title=?, nft_image_url=?, nft_description=?, nft_owner_label=? WHERE id=?",
                    (info.title.strip()[:200] or nft_slug, info.image_url, info.description, info.owner_label, offer_id),
                )
                await db.conn.commit()
                logger.info("NFT resolved for offer %s: %s", offer_id, info.image_url)
        except Exception as exc:
            logger.warning("NFT resolve failed for %s: %s", nft_slug, exc)
    asyncio.ensure_future(_resolve_bg())'''

assert old in s, "block not found"
s = s.replace(old, new, 1)

# Update chosen_inline_result to refresh the card
old2 = '''@router.chosen_inline_result()
async def on_chosen_inline_result(
    chosen: ChosenInlineResult,
    db: Database,
    service: DealService,
) -> None:
    try:
        offer_id = int(chosen.result_id)
    except (TypeError, ValueError):
        return
    if chosen.inline_message_id:
        await db.set_inline_message(offer_id, chosen.inline_message_id)
        # Обновить карточку с полными данными NFT
        try:
            await service._refresh_card(offer_id)
        except Exception as exc:
            logger.warning("Refresh after chosen failed: %s", exc)'''
new2 = '''@router.chosen_inline_result()
async def on_chosen_inline_result(
    chosen: ChosenInlineResult,
    db: Database,
    service: DealService,
) -> None:
    try:
        offer_id = int(chosen.result_id)
    except (TypeError, ValueError):
        return
    if chosen.inline_message_id:
        await db.set_inline_message(offer_id, chosen.inline_message_id)
        # Обновить карточку с полными данными NFT
        try:
            await service._refresh_card(offer_id)
        except Exception as exc:
            logger.warning("Refresh after chosen failed: %s", exc)'''
# old2 should already be in s, no change needed
p.write_text(s, encoding="utf-8")
print("done")
import ast
ast.parse(s)
print("SYNTAX OK")
