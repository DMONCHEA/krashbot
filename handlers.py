# handlers.py
import re
import json
import io
import csv
from typing import Dict, Tuple, Any, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, InputFile
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime, timedelta
from collections import defaultdict
from calendar import monthrange
from config import logger, PRODUCTS, PRODUCTS_BY_TITLE, DELIVERY_TIME_INTERVALS, REGISTER_ORG, REGISTER_CONTACT, ENTER_QUANTITY, ADMIN_IDS
from db import Database

class BotHandlers:
    __slots__ = ['db', 'user_carts', 'current_editing', 'selected_dates', 'last_orders', 'pending_product']

    def __init__(self, db: Database):
        self.db = db
        self.user_carts: Dict[int, Dict[str, Any]] = {}
        self.current_editing: Dict[int, int] = {}
        self.selected_dates: Dict[int, str] = {}
        self.last_orders: Dict[int, Dict[str, Any]] = {}
        self.pending_product: Dict[int, Dict[str, Any]] = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            user = update.effective_user
            logger.info(f"Processing /start for user {user.id} in chat {update.message.chat.type}")
            
            if update.message.chat.type != 'private':
                logger.info(f"User {user.id} attempted registration in non-private chat")
                await update.message.reply_text("Регистрация доступна только в приватном чате с ботом.")
                return ConversationHandler.END
            
            context.user_data.clear()
            logger.info(f"Cleared user_data for user {user.id}")
            
            organization, contact_person = self.db.get_client(user.id)
            if organization and contact_person:
                logger.info(f"User {user.id} already registered: {organization}, {contact_person}")
                await update.message.reply_text(
                    "Вы уже зарегистрированы. Меню товаров:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Открыть меню", switch_inline_query_current_chat="")]
                    ])
                )
                return ConversationHandler.END
            
            logger.info(f"User {user.id} not registered, entering REGISTER_ORG state")
            await update.message.reply_text(
                "Добро пожаловать! Для начала работы необходимо зарегистрироваться. "
                "Пожалуйста, введите название вашей организации:"
            )
            return REGISTER_ORG
        except Exception as e:
            logger.error(f"Error in start for user {user.id}: {str(e)}", exc_info=True)
            await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже.")
            return ConversationHandler.END

    async def register_org(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            user_id = update.message.from_user.id
            org = update.message.text.strip()
            logger.info(f"register_org called for user {user_id} with text '{org}'")
            
            if not org:
                logger.info(f"Organization name is empty for user {user_id}")
                await update.message.reply_text("Название организации не может быть пустым. Попробуйте снова:")
                return REGISTER_ORG
            
            if not re.match(r'^[А-Яа-яA-Za-z\s-]+$', org):
                logger.info(f"Organization name '{org}' does not match regex for user {user_id}")
                await update.message.reply_text("Название организации должно содержать только буквы, пробелы или дефисы. Попробуйте снова:")
                return REGISTER_ORG
            
            context.user_data['organization'] = org
            logger.info(f"Organization '{org}' saved for user {user_id}, moving to REGISTER_CONTACT")
            await update.message.reply_text("Теперь введите ваше контактное лицо (ФИО):")
            return REGISTER_CONTACT
        except Exception as e:
            logger.error(f"Error in register_org for user {user_id}: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "Произошла ошибка при обработке названия организации. "
                "Пожалуйста, попробуйте снова или обратитесь в поддержке."
            )
            return REGISTER_ORG

    async def register_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            user_id = update.message.from_user.id
            contact = update.message.text.strip()
            logger.info(f"register_contact called for user {user_id} with text '{contact}'")
            
            if not contact:
                logger.info(f"Contact person is empty for user {user_id}")
                await update.message.reply_text("ФИО не может быть пустым. Попробуйте снова:")
                return REGISTER_CONTACT
            
            if not re.match(r'^[А-Яа-яA-Za-z\s-]+$', contact):
                logger.info(f"Contact person '{contact}' does not match regex for user {user_id}")
                await update.message.reply_text("ФИО должно содержать только буквы, пробелы или дефисы. Попробуйте снова:")
                return REGISTER_CONTACT
            
            organization = context.user_data.get('organization')
            if not organization:
                logger.error(f"No organization found in user_data for user {user_id}")
                await update.message.reply_text("Ошибка: данные организации потеряны. Начните заново с /start.")
                return ConversationHandler.END
            
            self.db.add_client(user_id, organization, contact)
            logger.info(f"Registration completed for user {user_id}: {organization}, {contact}")
            await update.message.reply_text(
                "Регистрация завершена! Теперь вы можете заказывать продукты.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Открыть меню", switch_inline_query_current_chat="")]
                ])
            )
            context.user_data.clear()
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in register_contact for user {user_id}: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "Произошла ошибка при обработке ФИО. Пожалуйста, попробуйте снова или обратитесь в поддержку."
            )
            return REGISTER_CONTACT

    async def cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.message.from_user.id
        logger.info(f"User {user_id} cancelled registration")
        context.user_data.clear()
        self.pending_product.pop(user_id, None)
        await update.message.reply_text("Регистрация отменена. Начните заново с /start.")
        return ConversationHandler.END

    async def enter_quantity(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.message.from_user.id
        quantity_text = update.message.text.strip()
        logger.info(f"enter_quantity called for user {user_id} with text '{quantity_text}'")
        
        try:
            quantity = int(quantity_text)
            if quantity <= 0:
                await update.message.reply_text("Количество должно быть больше нуля. Пожалуйста, введите корректное количество:")
                return ENTER_QUANTITY
        except ValueError:
            logger.info(f"Invalid quantity input '{quantity_text}' for user {user_id}")
            await update.message.reply_text("Пожалуйста, введите число. Попробуйте снова:")
            return ENTER_QUANTITY
        
        if user_id not in self.pending_product:
            logger.error(f"No pending product for user {user_id}")
            await update.message.reply_text("Ошибка: товар не выбран. Начните заново, выбрав товар из меню.")
            return ConversationHandler.END
        
        product = self.pending_product[user_id]
        if user_id not in self.user_carts:
            self.user_carts[user_id] = {"items": []}
        
        cart = self.user_carts[user_id]["items"]
        for item in cart:
            if item["product"]["id"] == product["id"]:
                item["quantity"] += quantity
                break
        else:
            cart.append({"product": product, "quantity": quantity})
        
        self.current_editing[user_id] = len(cart) - 1
        self.pending_product.pop(user_id, None)
        
        await self.show_cart(update, context, user_id)
        return ConversationHandler.END

    async def check_client_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.from_user.id
        organization, contact_person = self.db.get_client(user_id)
        if organization and contact_person:
            await update.message.reply_text(
                f"Ваши данные:\nОрганизация: {organization}\nКонтактное лицо: {contact_person}"
            )
        else:
            await update.message.reply_text("Вы не зарегистрированы. Пожалуйста, используйте /start для регистрации.")

    async def inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.inline_query.query.lower()
        results = [
            InlineQueryResultArticle(
                id=product["id"],
                title=product["title"],
                description=product["description"],
                thumbnail_url=product["thumb_url"],
                input_message_content=InputTextMessageContent(
                    f"{product['title']}\n{product['description']}"
                )
            ) for product in PRODUCTS if query in product["title"].lower()
        ]
        await update.inline_query.answer(results)

    async def handle_product_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.message.from_user.id
        logger.info(f"handle_product_message called for user {user_id} with text '{update.message.text}' in chat {update.message.chat.type}")
        
        organization, contact_person = self.db.get_client(user_id)
        if not organization:
            logger.info(f"User {user_id} is not registered, ignoring product message")
            await update.message.reply_text("Пожалуйста, завершите регистрацию с помощью команды /start")
            return ConversationHandler.END
        
        message_text = update.message.text.strip()
        first_line = message_text.split('\n', 1)[0].strip()
        
        product = PRODUCTS_BY_TITLE.get(first_line)
        if product:
            self.pending_product[user_id] = product
            await update.message.reply_text(f"Вы выбрали: {product['title']}. Введите количество:")
            return ENTER_QUANTITY
        else:
            await update.message.reply_text("Такой продукт не найден. Попробуйте снова.")
            return ConversationHandler.END

    async def show_cart(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, edit_message: bool = False):
        cart_items = self.user_carts.get(user_id, {}).get("items", [])
        if not cart_items:
            text = "Ваша корзина пуста!"
            if edit_message:
                await update.callback_query.edit_message_text(text=text)
            else:
                await update.message.reply_text(text)
            return
        
        editing_index = self.current_editing.get(user_id, 0)
        items_text = [
            f"{'➡️ ' if idx == editing_index else '▪️ '}{item['product']['title']}\n"
            f"Описание: {item['product']['description']}\n"
            f"Количество: {item['quantity']}"
            for idx, item in enumerate(cart_items)
        ]
        
        response = "🛒 Ваша корзина:\n\n" + "\n\n".join(items_text)
        
        buttons = []
        if cart_items:
            buttons.append([
                InlineKeyboardButton("◀️", callback_data="prev_item"),
                InlineKeyboardButton("▶️", callback_data="next_item"),
            ])
        
        buttons.extend([
            [
                InlineKeyboardButton("❌ Удалить", callback_data="remove_item"),
                InlineKeyboardButton("🚚 Доставка", callback_data="select_delivery_date")
            ],
            [
                InlineKeyboardButton("➕ Добавить еще", switch_inline_query_current_chat=""),
                InlineKeyboardButton("👨‍💼 Менеджер", url="https://t.me/Krash_order_Bot")
            ]
        ])
        
        if edit_message:
            await update.callback_query.edit_message_text(
                text=response,
                reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text(
                response,
                reply_markup=InlineKeyboardMarkup(buttons))

    async def show_delivery_dates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        today = datetime.now()
        dates = [(today + timedelta(days=i)).strftime("%d.%m") for i in range(1, 8)]
        date_keys = [f"delivery_date_{(today + timedelta(days=i)).strftime('%Y-%m-%d')}" for i in range(1, 8)]
        keyboard = [
            [InlineKeyboardButton(dates[i], callback_data=date_keys[i]) for i in range(j, min(j+3, 7))]
            for j in range(0, 7, 3)
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_cart")])
        await update.callback_query.edit_message_text(
            text="📅 Выберите дату доставки:\n\nДоступные даты на ближайшую неделю:",
            reply_markup=InlineKeyboardMarkup(keyboard))

    async def show_delivery_times(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton(DELIVERY_TIME_INTERVALS[i], callback_data=f"delivery_time_{DELIVERY_TIME_INTERVALS[i]}") 
             for i in range(j, min(j+2, len(DELIVERY_TIME_INTERVALS)))]
            for j in range(0, len(DELIVERY_TIME_INTERVALS), 2)
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_dates")])
        
        await update.callback_query.edit_message_text(
            text="🕒 Выберите интервал доставки:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def process_delivery_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        time_str = query.data.split("_", 2)[-1]
        date_str = self.selected_dates.get(user_id)
        
        if not date_str:
            await query.answer("Ошибка: дата не выбрана")
            return
        
        organization, contact_person = self.db.get_client(user_id)
        if not organization:
            await query.edit_message_text("Перед оформлением заказа необходимо зарегистрироваться!")
            return
        
        cart = self.user_carts.get(user_id, {}).get("items", [])
        if not cart:
            await query.edit_message_text("Ваша корзина пуста!")
            return
            
        order_lines = [f"▪️ {item['product']['title']} - {item['quantity']} шт." for item in cart]
        
        delivery_date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        start_time_str = time_str.split(" - ")[0]
        delivery_datetime = datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        
        delivery_info = (
            f"\n📅 Дата доставки: {delivery_date_obj.strftime('%d.%m.%Y')}\n"
            f"🕒 Время доставки: {time_str}\n"
        )
        
        order_text = "✅ Ваш заказ оформлен!\n\n" + "\n".join(order_lines) + delivery_info

        order_data = {
            "items": [{"product": item["product"], "quantity": item["quantity"]} for item in cart],
            "organization": organization,
            "contact_person": contact_person,
            "username": query.from_user.username
        }
        
        try:
            order_id = self.db.save_order(user_id, order_data, date_str, time_str)
            logger.info(f"Order #{order_id} saved successfully for user {user_id}")
        except Exception as e:
            logger.error(f"Error saving order: {e}")
            await query.edit_message_text("Произошла ошибка при сохранении заказа. Пожалуйста, попробуйте позже.")
            return
        
        self.last_orders[user_id] = {
            "order_id": order_id,
            "order_text": order_text,
            "delivery_datetime": delivery_datetime,
            "admin_message_ids": {}
        }
        
        keyboard = [
            [InlineKeyboardButton("❌ Отменить заказ", callback_data="cancel_last_order")],
            [InlineKeyboardButton("👨‍💼 Связаться с менеджером", url="https://t.me/Krash_order_Bot")]
        ]
        
        time_left = delivery_datetime - datetime.now()
        if time_left <= timedelta(hours=6):
            order_text += "\n\n⚠️ Отмена заказа возможна не позднее чем за 6 часов до доставки. Сейчас отменить заказ уже нельзя."
            keyboard = [[InlineKeyboardButton("👨‍💼 Связаться с менеджером", url="https://t.me/Krash_order_Bot")]]
        
        await query.edit_message_text(
            text=order_text + "\nДля уточнения деталей с вами свяжется менеджер.",
            reply_markup=InlineKeyboardMarkup(keyboard))
        
        if ADMIN_IDS:
            admin_message = (
                f"=== НОВЫЙ ЗАКАЗ ===\n\n"
                f"🏢 Организация: {organization}\n"
                f"👤 Контакт: {contact_person}\n"
                f"📱 Телеграм: @{query.from_user.username if query.from_user.username else 'не указан'}\n"
                f"📅 Доставка: {delivery_date_obj.strftime('%d.%m.%Y')} {time_str}\n"
                f"🆔 Номер заказа: {order_id}\n\n"
                "Состав заказа:\n" + "\n".join(order_lines)
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    kb = [[InlineKeyboardButton("📨 Написать клиенту", url=f"https://t.me/{query.from_user.username}")]] if query.from_user.username else None
                    message = await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        reply_markup=InlineKeyboardMarkup(kb) if kb else None,
                        disable_notification=True
                    )
                    self.last_orders[user_id]["admin_message_ids"][admin_id] = message.message_id
                    logger.info(f"Уведомление отправлено в чат {admin_id}, message_id: {message.message_id}")
                except Exception as e:
                    logger.error(f"Ошибка отправки в чат {admin_id}: {e}")
        
        self.user_carts[user_id] = {"items": []}
        self.selected_dates.pop(user_id, None)

    async def cancel_last_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if user_id not in self.last_orders:
            await query.edit_message_text(text="У вас нет активных заказов для отмены.")
            return
        
        order_data = self.last_orders[user_id]
        delivery_datetime = order_data["delivery_datetime"]
        time_left = delivery_datetime - datetime.now()
        
        if time_left <= timedelta(hours=6):
            order_text = order_data["order_text"].replace("✅ Ваш заказ оформлен!", "")
            await query.edit_message_text(
                text="⚠️ Отмена заказа возможна не позднее чем за 6 часов до доставки. Сейчас отменить заказ уже нельзя.\n\n" + 
                     order_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👨‍💼 Связаться с менеджером", url="https://t.me/Krash_order_Bot")]
                ])
            )
            return
        
        if not self.db.cancel_order(order_data["order_id"]):
            await query.edit_message_text(text="Не удалось отменить заказ. Пожалуйста, свяжитесь с менеджером.")
            return
        
        if ADMIN_IDS:
            cancel_message = (
                f"⚠️ ЗАКАЗ ОТМЕНЕН ⚠️\n\n"
                f"Заказ №{order_data['order_id']} был отменен клиентом.\n"
                f"Оригинальное сообщение:\n\n{order_data['order_text']}"
            )
            for admin_id in ADMIN_IDS:
                try:
                    reply_to_message_id = order_data["admin_message_ids"].get(admin_id)
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=cancel_message,
                        reply_to_message_id=reply_to_message_id,
                        disable_notification=True
                    )
                    logger.info(f"Уведомление об отмене заказа #{order_data['order_id']} отправлено в чат {admin_id}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления об отмене в чат {admin_id}: {e}")

        order_text = order_data["order_text"].replace("✅ Ваш заказ оформлен!", "")
        await query.edit_message_text(
            text="❌ Заказ отменен\n\n" + order_text,
            reply_markup=None
        )
        
        del self.last_orders[user_id]

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        try:
            if data == "prev_item":
                if user_id in self.current_editing:
                    cart = self.user_carts.get(user_id, {}).get("items", [])
                    if cart:
                        self.current_editing[user_id] = (self.current_editing[user_id] - 1) % len(cart)
                        await self.show_cart(update, context, user_id, edit_message=True)
            
            elif data == "next_item":
                if user_id in self.current_editing:
                    cart = self.user_carts.get(user_id, {}).get("items", [])
                    if cart:
                        self.current_editing[user_id] = (self.current_editing[user_id] + 1) % len(cart)
                        await self.show_cart(update, context, user_id, edit_message=True)
            
            elif data == "remove_item":
                if user_id in self.current_editing:
                    idx = self.current_editing[user_id]
                    cart = self.user_carts.get(user_id, {}).get("items", [])
                    if idx < len(cart):
                        del cart[idx]
                        if cart:
                            self.current_editing[user_id] = min(idx, len(cart) - 1)
                        else:
                            del self.current_editing[user_id]
                        await self.show_cart(update, context, user_id, edit_message=True)
            
            elif data == "select_delivery_date":
                await self.show_delivery_dates(update, context)
            
            elif data == "back_to_cart":
                await self.show_cart(update, context, user_id, edit_message=True)
            
            elif data == "back_to_dates":
                await self.show_delivery_dates(update, context)
            
            elif data.startswith("delivery_date_"):
                date_str = data.split("_", 2)[-1]
                self.selected_dates[user_id] = date_str
                await self.show_delivery_times(update, context)
            
            elif data.startswith("delivery_time_"):
                await self.process_delivery_time(update, context)
            
            elif data == "cancel_last_order":
                await self.cancel_last_order(update, context)
            
            elif data == "my_orders":
                await self.show_active_orders(update, context)
            
            elif data == "catalog":
                await query.edit_message_text(
                    text="Меню товаров:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                        "Открыть меню", switch_inline_query_current_chat=""
                    )]])
                )
            
            elif data == "about":
                await query.edit_message_text(
                    text="ℹ️ О нас:\n\nМы доставляем свежие круассаны и выпечку каждое утро!\n\n"
                         "Работаем с 6:00 до 13:00\n"
                         "По вопросам сотрудничества: @Krash_order_Bot",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")]])
                )
            
            elif data == "back_to_menu":
                await self.show_main_menu(update)
        
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await query.edit_message_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

    async def show_active_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        order = self.db.get_active_order(user_id)
        
        if not order:
            await query.edit_message_text(
                text="У вас нет активных заказов.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")]])
            )
            return
        
        order_lines = [f"▪️ {item['product']['title']} - {item['quantity']} шт." for item in order["order_data"]["items"]]
        
        order_text = (
            "📦 Ваш активный заказ:\n\n" +
            "\n".join(order_lines) +
            f"\n\n📅 Дата доставки: {order['delivery_date']}" +
            f"\n🕒 Время доставки: {order['delivery_time']}"
        )
        
        keyboard = []
        delivery_datetime = datetime.strptime(
            f"{order['delivery_date']} {order['delivery_time'].split(' - ')[0]}",
            "%Y-%m-%d %H:%M"
        )
        time_left = delivery_datetime - datetime.now()
        
        if time_left > timedelta(hours=6):
            keyboard.append([InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_order_{order['order_id']}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")])
        
        await query.edit_message_text(
            text=order_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.from_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("Эта команда доступна только администраторам.")
            return
        
        now = datetime.now()
        is_month = False
        start_date = None
        end_date = None
        
        if context.args:
            date_input = context.args[0].strip()
            parts = date_input.split('.')
            if len(parts) != 2:
                await update.message.reply_text("Некорректный формат. Используйте DD.MM для дня или MM.YYYY для месяца.")
                return
            
            try:
                if len(parts[1]) == 2:  # DD.MM
                    day, month = map(int, parts)
                    year = now.year
                    target_date = datetime(year, month, day)
                    start_date = end_date = target_date.strftime("%Y-%m-%d")
                    period_display = f"Данные за {target_date.strftime('%d.%m')}"
                elif len(parts[1]) == 4:  # MM.YYYY
                    month, year = map(int, parts)
                    is_month = True
                    _, last_day = monthrange(year, month)
                    start_date = datetime(year, month, 1).strftime("%Y-%m-%d")
                    end_date = datetime(year, month, last_day).strftime("%Y-%m-%d")
                    period_display = f"Данные с {datetime(year, month, 1).strftime('%d.%m')} по {datetime(year, month, last_day).strftime('%d.%m')}"
                else:
                    await update.message.reply_text("Некорректный формат. Используйте DD.MM для дня или MM.YYYY для месяца.")
                    return
            except ValueError:
                await update.message.reply_text("Некорректный формат даты. Используйте DD.MM для дня или MM.YYYY для месяца.")
                return
        else:
            is_month = True
            year = now.year
            month = now.month
            _, last_day = monthrange(year, month)
            start_date = datetime(year, month, 1).strftime("%Y-%m-%d")
            end_date = datetime(year, month, last_day).strftime("%Y-%m-%d")
            period_display = f"Данные с {datetime(year, month, 1).strftime('%d.%m')} по {datetime(year, month, last_day).strftime('%d.%m')}"
        
        conn = self.db.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        delivery_date,
                        (order_data->>'organization') as organization,
                        (order_data->>'contact_person') as contact_person,
                        jsonb_agg(jsonb_build_object(
                            'product_id', (item->'product'->>'id')::int,
                            'quantity', (item->>'quantity')::int
                        )) as items
                    FROM orders,
                    jsonb_array_elements(order_data->'items') as item
                    WHERE delivery_date BETWEEN %s AND %s AND status = 'active'
                    GROUP BY delivery_date, organization, contact_person
                """, (start_date, end_date))
                aggregated_data = cursor.fetchall()
        except Exception as e:
            logger.error(f"Error fetching aggregated orders: {e}")
            await update.message.reply_text("Ошибка при получении данных. Попробуйте позже.")
            return
        finally:
            self.db.put_connection(conn)
        
        if not aggregated_data:
            await update.message.reply_text(f"Нет активных заказов за период {period_display}.")
            return
        
        csvfile = io.StringIO()
        writer = csv.writer(csvfile, dialect='excel', delimiter=',')
        
        writer.writerow([period_display] + [''] * 14)
        headers = [
            'Дата', 'Клиент', 'Организация', 
            'Классический', 'Миндальный', 'Заморозка/10шт', 'Пан-о-шоколя', 
            'Ванильный', 'Шоколадный', 'Матча', 'Мини', 
            'Улитка/Изюм', 'Улитка/Мак', 'Булка/Кардамон', 
            'Комбо1', 'Комбо2'
        ]
        writer.writerow(headers)
        
        totals = [0] * 13
        date_user_orders = defaultdict(lambda: defaultdict(list))
        for row in aggregated_data:
            delivery_date = row['delivery_date']
            contact = row['contact_person']
            org = row['organization']
            quantities = [0] * 13
            for item in row['items']:
                prod_id = item['product_id'] - 1
                if 0 <= prod_id < 13:
                    quantities[prod_id] += item['quantity']
            date_user_orders[delivery_date][(contact, org)] = quantities
        
        sorted_dates = sorted(date_user_orders.keys())
        for date_str in sorted_dates:
            user_data = date_user_orders[date_str]
            sorted_users = sorted(user_data.keys(), key=lambda x: x[0])
            for (contact, org), quantities in sorted_users:
                date_dd_mm = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
                writer.writerow([date_dd_mm, contact, org] + quantities)
                for i in range(13):
                    totals[i] += quantities[i]
        
        writer.writerow(['Итого', '', ''] + totals)
        
        csvfile.seek(0)
        filename = f"orders_{start_date.replace('-', '')}_{end_date.replace('-', '')}.csv"
        await update.message.reply_document(
            document=InputFile(csvfile, filename=filename)
        )

    async def add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.from_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("Эта команда доступна только администраторам.")
            return
        
        if not context.args:
            await update.message.reply_text("Укажите ID пользователя для добавления в админы: /add_admin <user_id>")
            return
        
        try:
            new_admin_id = int(context.args[0])
            if new_admin_id not in ADMIN_IDS:
                ADMIN_IDS.append(new_admin_id)
                await update.message.reply_text(f"Пользователь {new_admin_id} добавлен в админы.")
            else:
                await update.message.reply_text("Этот пользователь уже администратор.")
        except ValueError:
            await update.message.reply_text("Некорректный ID пользователя.")

    async def remove_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.from_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("Эта команда доступна только администраторам.")
            return
        
        if not context.args:
            await update.message.reply_text("Укажите ID пользователя для удаления из админов: /remove_admin <user_id>")
            return
        
        try:
            admin_id = int(context.args[0])
            if admin_id in ADMIN_IDS:
                ADMIN_IDS.remove(admin_id)
                await update.message.reply_text(f"Пользователь {admin_id} удалён из админов.")
            else:
                await update.message.reply_text("Этот пользователь не является администратором.")
        except ValueError:
            await update.message.reply_text("Некорректный ID пользователя.")

    async def show_main_menu(self, update: Update):
        await update.callback_query.edit_message_text(
            text="Выберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Каталог", callback_data="catalog")],
                [InlineKeyboardButton("📦 Мои заказы", callback_data="my_orders")],
                [InlineKeyboardButton("ℹ️ О нас", callback_data="about")]
            ])
        )