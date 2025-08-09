from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update, 
    InlineQueryResultArticle, 
    InputTextMessageContent
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    InlineQueryHandler, 
    MessageHandler, 
    filters, 
    CallbackQueryHandler,
    ConversationHandler
)
from datetime import datetime, timedelta
import sqlite3
import os

# Состояния для ConversationHandler
REGISTER_ORG, REGISTER_CONTACT = range(2)

TOKEN = "8001692362:AAGTBIg5sG8y-dqG-oRVBjRMcN9uWp4A1DQ"
SECOND_CHAT_ID = -4903587461  # Чат для уведомлений

# Инициализация базы данных клиентов
def init_db():
    conn = sqlite3.connect('clients.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS clients
                      (user_id INTEGER PRIMARY KEY,
                       organization TEXT NOT NULL,
                       contact_person TEXT)''')
    conn.commit()
    conn.close()

init_db()

def save_client(user_id, organization, contact_person):
    """Сохраняет данные клиента в базу"""
    conn = sqlite3.connect('clients.db')
    cursor = conn.cursor()
    cursor.execute('''INSERT OR REPLACE INTO clients 
                      VALUES (?, ?, ?)''', 
                   (user_id, organization, contact_person))
    conn.commit()
    conn.close()

def get_client(user_id):
    """Получает данные клиента из базы"""
    conn = sqlite3.connect('clients.db')
    cursor = conn.cursor()
    cursor.execute('''SELECT organization, contact_person 
                      FROM clients WHERE user_id=?''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result or (None, None)

# Товары с фото (без цен)
PRODUCTS = [
    {"id": "1", "title": "Классический круассан", "description": "75 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/1twHpy00/image.png"},
    {"id": "2", "title": "Миндальный круассан", "description": "146 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/qMkL3VNn/image.jpg"},
    {"id": "3", "title": "Круассан в заморозке", "description": "(Упаковка 10 шт.) 930 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/0N6ZyYbB/image.png"},
    {"id": "4", "title": "Пан-о-шоколя", "description": "65 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/htv12Lbt/image.jpg"},
    {"id": "5", "title": "Круассан ванильный крем", "description": "150 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/httpHWgg/image.jpg"},
    {"id": "6", "title": "Круассан шоколадный крем", "description": "150 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/nhWYgX0Y/image.jpg"},
    {"id": "7", "title": "Круассан матча крем", "description": "150 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/4x4DfnTH/image.jpg"},
    {"id": "8", "title": "Мини круассан классический", "description": "40 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/CLm4CP82/image.jpg"},
    {"id": "9", "title": "Улитка слоеная с изюмом", "description": "110 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/dVN4FHtC/image.jpg"},
    {"id": "10", "title": "Улитка слоеная с маком", "description": "110 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/mZ3jk2gB/image.png"},
    {"id": "11", "title": "Слоеная булочка с кардамоном", "description": "65 г", "photo_url": "", "thumb_url": "https://i.postimg.cc/XvTLGr57/image.png"},
    {"id": "12", "title": "Комбо 1: Круассан классический + джем/масло", "description": "", "photo_url": "", "thumb_url": "https://i.postimg.cc/FzvxpwGM/1.png"},
    {"id": "13", "title": "Комбо 2: круассан классический + джем + масло", "description": "", "photo_url": "", "thumb_url": "https://i.postimg.cc/T1cJ4Q4p/2.png"}
]

# Словарь для быстрого поиска товаров
PRODUCTS_BY_TITLE = {p["title"]: p for p in PRODUCTS}

# Хранилища данных
user_carts = {}
current_editing = {}
selected_dates = {}
last_orders = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    organization, contact_person = get_client(user.id)
    
    if organization:
        await show_main_menu(update)
    else:
        await update.message.reply_text(
            "Добро пожаловать! Для начала работы необходимо зарегистрироваться.\n"
            "Пожалуйста, введите название вашей организации:"
        )
        return REGISTER_ORG

async def register_org(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['organization'] = update.message.text
    await update.message.reply_text("Теперь введите ваше контактное лицо (ФИО):")
    return REGISTER_CONTACT

async def register_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    organization = context.user_data['organization']
    contact_person = update.message.text
    
    save_client(user.id, organization, contact_person)
    await update.message.reply_text(
        f"✅ Регистрация завершена!\n\n"
        f"Организация: {organization}\n"
        f"Контактное лицо: {contact_person}"
    )
    await show_main_menu(update)
    return ConversationHandler.END

async def show_main_menu(update: Update):
    await update.message.reply_text(
        "Меню товаров:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Открыть меню", switch_inline_query_current_chat="")
        ]])
    )

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Регистрация отменена. Используйте /start для повторной регистрации.")
    return ConversationHandler.END

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.inline_query.from_user.id
    organization, _ = get_client(user_id)
    
    if not organization:
        await update.inline_query.answer([])
        await context.bot.send_message(
            chat_id=user_id,
            text="Для заказа товаров необходимо сначала зарегистрироваться через /start"
        )
        return
    
    results = [
        InlineQueryResultArticle(
            id=p["id"],
            title=p["title"],
            description=p['description'],
            input_message_content=InputTextMessageContent(
                f"{p['title']}\n{p['description']}"
            ),
            thumbnail_url=p["thumb_url"],
            thumbnail_width=100,
            thumbnail_height=100
        )
        for p in PRODUCTS
    ]
    await update.inline_query.answer(results, cache_time=3600)

async def handle_product_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    organization, _ = get_client(user_id)
    
    if not organization:
        await update.message.reply_text("Для заказа товаров необходимо сначала зарегистрироваться через /start")
        return
    
    await update.message.delete()
    message_text = update.message.text
    first_line = message_text.split('\n', 1)[0].strip()
    
    if (product := PRODUCTS_BY_TITLE.get(first_line)):
        if user_id not in user_carts:
            user_carts[user_id] = {"items": []}
        
        cart = user_carts[user_id]["items"]
        for item in cart:
            if item["product"]["id"] == product["id"]:
                item["quantity"] += 1
                break
        else:
            cart.append({"product": product, "quantity": 1})
        
        current_editing[user_id] = len(cart) - 1
        await show_cart(update, user_id)

async def show_cart(update: Update, user_id: int, edit_message: bool = False):
    if not user_carts.get(user_id, {}).get("items"):
        return
    
    cart = user_carts[user_id]["items"]
    editing_index = current_editing.get(user_id, 0)
    items_text = []
    
    for idx, item in enumerate(cart):
        p = item["product"]
        qty = item["quantity"]
        
        prefix = "➡️ " if idx == editing_index else "▪️ "
        items_text.append(
            f"{prefix}{p['title']}\n"
            f"Описание: {p['description']}\n"
            f"Количество: {qty}"
        )
    
    response = "🛒 Ваша корзина:\n\n" + "\n\n".join(items_text)
    
    buttons = []
    if cart:
        editing_item = cart[editing_index]
        buttons.append([
            InlineKeyboardButton("◀️", callback_data="prev_item"),
            InlineKeyboardButton("-", callback_data="decrease"),
            InlineKeyboardButton(str(editing_item["quantity"]), callback_data="quantity"),
            InlineKeyboardButton("+", callback_data="increase"),
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

# Генерация дат доставки
DELIVERY_DATES = [(datetime.now() + timedelta(days=i)).strftime("%d.%m") for i in range(1, 8)]
DATE_KEYS = [f"delivery_date_{(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d')}" 
             for i in range(1, 8)]

async def show_delivery_dates(update: Update, user_id: int):
    keyboard = [
        [InlineKeyboardButton(DELIVERY_DATES[i], callback_data=DATE_KEYS[i]) 
         for i in range(0, 7, 3)],
        [InlineKeyboardButton(DELIVERY_DATES[i], callback_data=DATE_KEYS[i]) 
         for i in range(1, 7, 3)],
        [InlineKeyboardButton(DELIVERY_DATES[i], callback_data=DATE_KEYS[i]) 
         for i in range(2, 7, 3)],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_cart")]
    ]
    await update.callback_query.edit_message_text(
        text="📅 Выберите дату доставки:\n\nДоступные даты на ближайшую неделю:",
        reply_markup=InlineKeyboardMarkup(keyboard))

DELIVERY_TIME_INTERVALS = [
    "6:00 - 8:00",
    "6:30 - 8:30",
    "7:00 - 9:00", 
    "7:30 - 9:30", 
    "8:00 - 10:00",
    "8:30 - 10:30",
    "9:00 - 11:00",
    "9:30 - 11:30",
    "10:00 - 12:00",
    "10:30 - 12:30",
]

async def show_delivery_times(update: Update, user_id: int):
    keyboard = [
        [InlineKeyboardButton(interval, callback_data=f"delivery_time_{interval}") 
         for interval in DELIVERY_TIME_INTERVALS[i:i+2]]
        for i in range(0, len(DELIVERY_TIME_INTERVALS), 2)
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_dates")])
    
    await update.callback_query.edit_message_text(
        text="🕒 Выберите интервал доставки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_delivery_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    time_str = query.data.split("_", 2)[-1]
    date_str = selected_dates.get(user_id)
    
    if not date_str:
        await query.answer("Ошибка: дата не выбрана")
        return
    
    organization, contact_person = get_client(user.id)
    if not organization:
        await query.edit_message_text("Для оформления заказа необходимо зарегистрироваться через /start")
        return
    
    cart = user_carts[user_id]["items"]
    order_lines = []
    
    for item in cart:
        p = item["product"]
        qty = item["quantity"]
        order_lines.append(f"▪️ {p['title']} - {qty} шт.")
    
    delivery_date = datetime.strptime(date_str, "%Y-%m-%d")
    start_time_str = time_str.split(" - ")[0]
    delivery_datetime = datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
    
    delivery_info = (
        f"\n📅 Дата доставки: {delivery_date.strftime('%d.%m.%Y')}\n"
        f"🕒 Время доставки: {time_str}\n"
    )
    
    order_text = "✅ Ваш заказ оформлен!\n\n" + "\n".join(order_lines) + delivery_info
    
    last_orders[user_id] = {
        "order_text": order_text,
        "delivery_datetime": delivery_datetime
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
    
    admin_message = (
        f"=== НОВЫЙ ЗАКАЗ ===\n\n"
        f"🏢 Организация: {organization}\n"
        f"👤 Контакт: {contact_person}\n"
        f"📱 Телеграм: @{user.username if user.username else 'не указан'}\n"
        f"📅 Доставка: {delivery_date.strftime('%d.%m.%Y')} {time_str}\n\n"
        "Состав заказа:\n" + "\n".join(order_lines)
    )
    
    try:
        kb = [[InlineKeyboardButton("📨 Написать клиенту", url=f"https://t.me/{user.username}")]] if user.username else None
        sent_message = await context.bot.send_message(
            chat_id=SECOND_CHAT_ID,
            text=admin_message,
            reply_markup=InlineKeyboardMarkup(kb) if kb else None,
            disable_notification=True
        )
        last_orders[user_id]["admin_message_id"] = sent_message.message_id
    except Exception as e:
        print(f"Ошибка при отправке уведомления: {e}")
    
    user_carts[user_id] = {"items": []}
    selected_dates.pop(user_id, None)

async def cancel_last_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id not in last_orders:
        await query.edit_message_text(text="У вас нет активных заказов для отмены.")
        return
    
    order_data = last_orders[user_id]
    delivery_datetime = order_data["delivery_datetime"]
    time_left = delivery_datetime - datetime.now()
    
    if time_left <= timedelta(hours=6):
        order_text = "\n".join(order_data["order_text"].split("\n")[1:])
        await query.edit_message_text(
            text="⚠️ Отмена заказа возможна не позднее чем за 6 часов до доставки. Сейчас отменить заказ уже нельзя.\n\n" + 
                 order_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👨‍💼 Связаться с менеджером", url="https://t.me/Krash_order_Bot")]
            ])
        )
        return
    
    try:
        admin_message = (
            f"=== ЗАКАЗ ОТМЕНЕН ===\n\n"
            f"👤 Клиент: {query.from_user.full_name}\n"
            f"📱 Телеграм: @{query.from_user.username if query.from_user.username else 'не указан'}\n\n"
            f"Заказ отменен пользователем."
        )
        
        await context.bot.send_message(
            chat_id=SECOND_CHAT_ID,
            text=admin_message,
            reply_to_message_id=order_data.get("admin_message_id"),
            disable_notification=True
        )
    except Exception as e:
        print(f"Ошибка при отправке уведомления об отмене: {e}")
    
    del last_orders[user_id]
    
    order_text = "\n".join(order_data["order_text"].split("\n")[1:])
    
    await query.edit_message_text(
        text="❌ Ваш заказ был отменен.\n\n" + order_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Сделать новый заказ", switch_inline_query_current_chat="")]
        ])
    )

async def handle_quantity_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if data == "cancel_last_order":
        await cancel_last_order(update, context)
        return
        
    if not user_carts.get(user_id, {}).get("items"):
        await query.edit_message_text(text="Ваша корзина пуста!")
        return
    
    if data == "select_delivery_date":
        await show_delivery_dates(update, user_id)
        return
        
    elif data.startswith("delivery_date_"):
        selected_dates[user_id] = data.split("_", 2)[-1]
        await show_delivery_times(update, user_id)
        return
        
    elif data.startswith("delivery_time_"):
        await process_delivery_time(update, context)
        return
        
    elif data == "back_to_cart":
        await show_cart(update, user_id, edit_message=True)
        return
        
    elif data == "back_to_dates":
        await show_delivery_dates(update, user_id)
        return
    
    cart = user_carts[user_id]["items"]
    idx = current_editing[user_id]
    
    if data == "increase":
        cart[idx]["quantity"] += 1
        
    elif data == "decrease" and cart[idx]["quantity"] > 1:
        cart[idx]["quantity"] -= 1
        
    elif data == "prev_item":
        current_editing[user_id] = (idx - 1) % len(cart)
        
    elif data == "next_item":
        current_editing[user_id] = (idx + 1) % len(cart)
        
    elif data == "remove_item":
        cart.pop(idx)
        if not cart:
            await query.edit_message_text(text="Ваша корзина пуста!")
            return
        current_editing[user_id] = min(idx, len(cart) - 1)
    
    await show_cart(update, user_id, edit_message=True)

async def check_client_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    organization, contact_person = get_client(update.message.from_user.id)
    
    if organization:
        await update.message.reply_text(
            f"Ваши данные:\n\n"
            f"🏢 Организация: {organization}\n"
            f"👤 Контактное лицо: {contact_person}"
        )
    else:
        await update.message.reply_text(
            "Вы еще не зарегистрированы!\n"
            "Используйте /start для регистрации"
        )

def main():
    app = Application.builder().token(TOKEN).build()
    
    # Обработчик регистрации
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            REGISTER_ORG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_org)],
            REGISTER_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_contact)],
        },
        fallbacks=[CommandHandler('cancel', cancel_registration)]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("myinfo", check_client_info))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_message))
    app.add_handler(CallbackQueryHandler(handle_quantity_buttons))
    
    app.run_polling()

if __name__ == "__main__":
    main()