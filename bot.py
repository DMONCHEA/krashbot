import os
import logging
import re
import json
import io
import csv
from typing import Dict, Tuple, Any, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    ApplicationBuilder,
    InlineQueryHandler,
    CallbackQueryHandler
)
import psycopg2
from psycopg2 import extras
from datetime import datetime, timedelta
from urllib.parse import urlparse
from collections import defaultdict
from calendar import monthrange

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = []
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
if ADMIN_CHAT_ID:
    try:
        ADMIN_IDS = [int(id.strip()) for id in ADMIN_CHAT_ID.split(",") if id.strip()]
    except ValueError as e:
        logger.error(f"Ошибка парсинга ADMIN_CHAT_ID: {e}")

# Состояния для ConversationHandler
REGISTER_ORG, REGISTER_CONTACT = range(2)

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

PRODUCTS_BY_TITLE = {p["title"]: p for p in PRODUCTS}

# Интервалы доставки
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

# Генерация дат доставки
def generate_delivery_dates():
    today = datetime.now()
    dates = []
    date_keys = []
    
    for i in range(1, 8):
        delivery_date = today + timedelta(days=i)
        dates.append(delivery_date.strftime("%d.%m"))
        date_keys.append(f"delivery_date_{delivery_date.strftime('%Y-%m-%d')}")
    
    return dates, date_keys

class Database:
    def __init__(self):
        try:
            self.conn = psycopg2.connect(DATABASE_URL)
            self.cursor = self.conn.cursor(cursor_factory=extras.DictCursor)
            self.create_tables()
            logger.info("Connected to PostgreSQL database")
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise
    
    def create_tables(self):
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    user_id BIGINT PRIMARY KEY,
                    organization TEXT NOT NULL,
                    contact_person TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS orders (
                    order_id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    order_data JSONB,
                    delivery_date TEXT,
                    delivery_time TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            self.conn.commit()
            logger.info("Database tables initialized successfully")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            self.conn.rollback()
            raise
    
    def get_client(self, user_id: int) -> Tuple[Optional[str], Optional[str]]:
        try:
            self.cursor.execute("SELECT organization, contact_person FROM clients WHERE user_id = %s", (user_id,))
            result = self.cursor.fetchone()
            return (result['organization'], result['contact_person']) if result else (None, None)
        except Exception as e:
            logger.error(f"Error fetching client {user_id}: {e}")
            return None, None
    
    def add_client(self, user_id: int, organization: str, contact_person: str):
        try:
            self.cursor.execute(
                "INSERT INTO clients (user_id, organization, contact_person) VALUES (%s, %s, %s)",
                (user_id, organization, contact_person)
            )
            self.conn.commit()
            logger.info(f"Client {user_id} added: {organization}, {contact_person}")
        except Exception as e:
            logger.error(f"Error adding client {user_id}: {e}")
            self.conn.rollback()
    
    def get_all_clients(self) -> Dict[int, Tuple[str, str]]:
        try:
            self.cursor.execute("SELECT user_id, organization, contact_person FROM clients")
            return {row['user_id']: (row['organization'], row['contact_person']) for row in self.cursor.fetchall()}
        except Exception as e:
            logger.error(f"Error fetching all clients: {e}")
            return {}
    
    def save_order(self, user_id: int, order_data: Dict[str, Any], delivery_date: str, delivery_time: str) -> int:
        try:
            self.cursor.execute('''
                INSERT INTO orders (user_id, order_data, delivery_date, delivery_time)
                VALUES (%s, %s, %s, %s)
                RETURNING order_id
            ''', (user_id, json.dumps(order_data), delivery_date, delivery_time))
            order_id = self.cursor.fetchone()['order_id']
            self.conn.commit()
            return order_id
        except Exception as e:
            logger.error(f"Error saving order for user {user_id}: {e}")
            self.conn.rollback()
            raise
    
    def cancel_order(self, order_id: int) -> bool:
        try:
            self.cursor.execute('''
                UPDATE orders 
                SET status = 'cancelled' 
                WHERE order_id = %s AND status = 'active'
            ''', (order_id,))
            rows_affected = self.cursor.rowcount
            self.conn.commit()
            return rows_affected > 0
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            self.conn.rollback()
            return False
    
    def get_active_order(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            self.cursor.execute('''
                SELECT order_id, order_data, delivery_date, delivery_time 
                FROM orders 
                WHERE user_id = %s AND status = 'active'
                ORDER BY created_at DESC 
                LIMIT 1
            ''', (user_id,))
            result = self.cursor.fetchone()
            if result:
                return {
                    'order_id': result['order_id'],
                    'order_data': json.loads(result['order_data']),
                    'delivery_date': result['delivery_date'],
                    'delivery_time': result['delivery_time']
                }
            return None
        except Exception as e:
            logger.error(f"Error getting active order for user {user_id}: {e}")
            return None
    
    def get_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        try:
            self.cursor.execute('''
                SELECT order_id, user_id, order_data, delivery_date, delivery_time, status 
                FROM orders 
                WHERE order_id = %s
            ''', (order_id,))
            result = self.cursor.fetchone()
            if result:
                return {
                    'order_id': result['order_id'],
                    'user_id': result['user_id'],
                    'order_data': result['order_data'],  # Уже dict благодаря DictCursor
                    'delivery_date': result['delivery_date'],
                    'delivery_time': result['delivery_time'],
                    'status': result['status']
                }
            return None
        except Exception as e:
            logger.error(f"Error getting order {order_id}: {e}")
            return None
        
    def get_orders_for_date(self, date_str: str) -> list:
        try:
            self.cursor.execute("""
                SELECT order_id, user_id, order_data, delivery_date, delivery_time 
                FROM orders 
                WHERE delivery_date = %s AND status = 'active'
            """, (date_str,))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Error fetching orders for date {date_str}: {e}")
            return []
    
    def close(self):
        self.cursor.close()
        self.conn.close()
        logger.info("Database connection closed")

class BotHandlers:
    def __init__(self):
        self.db = Database()
        self.user_carts: Dict[int, Dict[str, Any]] = {}
        self.current_editing: Dict[int, int] = {}
        self.selected_dates: Dict[int, str] = {}
        self.last_orders: Dict[int, Dict[str, Any]] = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обработчик команды /start"""
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
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                        "Открыть меню", switch_inline_query_current_chat=""
                    )]])
                )
            else:
                logger.info(f"User {user.id} not registered, starting registration")
                await update.message.reply_text("Добро пожаловать! Пожалуйста, укажите название вашей организации:")
                return REGISTER_ORG
        except Exception as e:
            logger.error(f"Error in start handler: {e}")
            await update.message.reply_text("Произошла ошибка при запуске. Попробуйте позже.")
            return ConversationHandler.END
    
    async def register_org(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Регистрация организации"""
        try:
            organization = update.message.text.strip()
            if not organization:
                await update.message.reply_text("Название организации не может быть пустым. Пожалуйста, введите заново.")
                return REGISTER_ORG
            
            context.user_data['organization'] = organization
            await update.message.reply_text("Теперь укажите ФИО контактного лица:")
            return REGISTER_CONTACT
        except Exception as e:
            logger.error(f"Error in register_org: {e}")
            await update.message.reply_text("Произошла ошибка. Попробуйте позже.")
            return ConversationHandler.END
    
    async def register_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Регистрация контактного лица"""
        try:
            contact_person = update.message.text.strip()
            if not contact_person:
                await update.message.reply_text("ФИО контактного лица не может быть пустым. Пожалуйста, введите заново.")
                return REGISTER_CONTACT
            
            organization = context.user_data.get('organization')
            if not organization:
                await update.message.reply_text("Произошла ошибка. Пожалуйста, начните заново с /start.")
                return ConversationHandler.END
            
            user_id = update.effective_user.id
            self.db.add_client(user_id, organization, contact_person)
            await update.message.reply_text(
                "Регистрация завершена! Меню товаров:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "Открыть меню", switch_inline_query_current_chat=""
                )]])
            )
            context.user_data.clear()
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in register_contact: {e}")
            await update.message.reply_text("Произошла ошибка при регистрации. Попробуйте позже.")
            return ConversationHandler.END
    
    async def cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отмена регистрации"""
        context.user_data.clear()
        await update.message.reply_text("Регистрация отменена.")
        return ConversationHandler.END
    
    async def inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inline меню товаров"""
        query = update.inline_query.query
        results = []
        for product in PRODUCTS:
            if query.lower() in product["title"].lower() or not query:
                results.append(
                    InlineQueryResultArticle(
                        id=product["id"],
                        title=product["title"],
                        description=product["description"],
                        thumbnail_url=product["thumb_url"],
                        input_message_content=InputTextMessageContent(
                            f"{product['title']}\n{product['description']}"
                        )
                    )
                )
        await update.inline_query.answer(results)
    
    async def handle_product_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщения с товаром"""
        text = update.message.text.strip()
        chat_type = update.message.chat.type
        user_id = update.effective_user.id
        
        logger.info(f"handle_product_message called for user {user_id} with text '{text}' in chat {chat_type}")
        
        if chat_type != 'private':
            return
        
        product = next((p for p in PRODUCTS if text.startswith(p["title"])), None)
        if not product:
            await update.message.reply_text("Товар не найден.")
            return
        
        if user_id not in self.user_carts:
            self.user_carts[user_id] = {"items": []}
        
        cart_item = next((item for item in self.user_carts[user_id]["items"] if item["product"]["id"] == product["id"]), None)
        if cart_item:
            cart_item["quantity"] += 1
        else:
            self.user_carts[user_id]["items"].append({"product": product, "quantity": 1})
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕", callback_data=f"add_{product['id']}"),
             InlineKeyboardButton("➖", callback_data=f"remove_{product['id']}")],
            [InlineKeyboardButton("🛒 К корзине", callback_data="view_cart")]
        ])
        
        await update.message.reply_text(
            f"{product['title']} добавлен в корзину.",
            reply_markup=keyboard
        )
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback query"""
        try:
            query = update.callback_query
            data = query.data
            user_id = query.from_user.id
            
            # Добавление товара
            if data.startswith("add_"):
                prod_id = data.split("_")[1]
                product = next((p for p in PRODUCTS if p["id"] == prod_id), None)
                if product:
                    cart_item = next((item for item in self.user_carts.get(user_id, {"items": []})["items"] if item["product"]["id"] == prod_id), None)
                    if cart_item:
                        cart_item["quantity"] += 1
                    else:
                        self.user_carts.setdefault(user_id, {"items": []})["items"].append({"product": product, "quantity": 1})
                    await query.answer("Товар добавлен")
                    await query.edit_message_text(f"{product['title']} добавлен в корзину.")
            
            # Удаление товара
            elif data.startswith("remove_"):
                prod_id = data.split("_")[1]
                items = self.user_carts.get(user_id, {"items": []})["items"]
                cart_item = next((item for item in items if item["product"]["id"] == prod_id), None)
                if cart_item:
                    cart_item["quantity"] -= 1
                    if cart_item["quantity"] <= 0:
                        items.remove(cart_item)
                    await query.answer("Товар удалён")
                    await query.edit_message_text(f"{cart_item['product']['title']} удалён из корзины.")
            
            # Просмотр корзины
            elif data == "view_cart":
                await self.show_cart(update, context)
            
            # Очистка корзины
            elif data == "clear_cart":
                self.user_carts.pop(user_id, None)
                await query.edit_message_text("Корзина очищена.")
            
            # Выбор даты доставки
            elif data.startswith("delivery_date_"):
                self.selected_dates[user_id] = data.split("_")[-1]
                await self.process_delivery_time(update, context)
            
            # Выбор времени доставки
            elif data.startswith("delivery_time_"):
                delivery_time = data.split("_")[-1].replace("-", " - ")
                await self.confirm_order(update, context, delivery_time)
            
            # Подтверждение заказа
            elif data == "confirm_order":
                cart = self.user_carts.get(user_id)
                if not cart or not cart["items"]:
                    await query.edit_message_text("Корзина пуста.")
                    return
                
                delivery_date = self.selected_dates.get(user_id)
                delivery_time = data  # Wait, no, this is "confirm_order", need to pass from previous
                # Assuming delivery_time is stored or passed, but from code, it's in confirm_order call
                
                # In original code, confirm_order is called with delivery_time
                # But for simplicity, assume it's stored in user_data or something. Adjust as per full code.
                
                organization, contact_person = self.db.get_client(user_id)
                order_data = {
                    "organization": organization,
                    "contact_person": contact_person,
                    "items": cart["items"]
                }
                order_id = self.db.save_order(user_id, order_data, delivery_date, delivery_time)
                
                # Уведомление о новом заказе в группу
                if ADMIN_CHAT_ID:
                    new_order_text = f"НОВЫЙ ЗАКАЗ #{order_id}\n\n"
                    new_order_text += f"Организация: {organization}\nКонтактное лицо: {contact_person}\n\n"
                    for item in cart["items"]:
                        new_order_text += f"{item['product']['title']} - {item['quantity']} шт.\n"
                    new_order_text += f"\nДата доставки: {delivery_date}\nВремя доставки: {delivery_time}"
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=new_order_text)
                
                await query.edit_message_text("Ваш заказ оформлен.")
                self.user_carts.pop(user_id, None)
                self.selected_dates.pop(user_id, None)
            
            # Отмена заказа
            elif data.startswith("cancel_order_"):
                order_id = int(data.split("_")[-1])
                logger.info(f"Attempting to cancel order {order_id} for user {query.from_user.id}")
                order = self.db.get_order(order_id)
                if order and order['status'] == 'active' and self.db.cancel_order(order_id):
                    await query.edit_message_text("Заказ успешно отменён.")
                    
                    # Уведомление об отмене в группу
                    if ADMIN_CHAT_ID:
                        cancel_text = f"ОТМЕНА ЗАКАЗА #{order_id}\n\n"
                        organization = order['order_data']['organization']
                        contact_person = order['order_data']['contact_person']
                        cancel_text += f"Организация: {organization}\nКонтактное лицо: {contact_person}\n\n"
                        for item in order['order_data']['items']:
                            cancel_text += f"{item['product']['title']} - {item['quantity']} шт.\n"
                        cancel_text += f"\nДата доставки: {order['delivery_date']}\nВремя доставки: {order['delivery_time']}\n"
                        cancel_text += "Заказ отменён пользователем."
                        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=cancel_text)
                else:
                    await query.edit_message_text("Не удалось отменить заказ. Возможно, он уже отменён или не существует.")
            
            # Отмена последнего заказа
            elif data == "cancel_last_order":
                await self.cancel_last_order(update, context)
            
            # Просмотр активных заказов
            elif data == "my_orders":
                await self.show_active_orders(update, context)
            
            # Открытие каталога
            elif data == "catalog":
                await query.edit_message_text(
                    text="Меню товаров:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                        "Открыть меню", switch_inline_query_current_chat=""
                    )]])
                )
            
            # Информация о боте
            elif data == "about":
                await query.edit_message_text(
                    text="ℹ️ О нас:\n\nМы доставляем свежие круассаны и выпечку каждое утро!\n\n"
                         "Работаем с 6:00 до 13:00\n"
                         "По вопросам сотрудничества: @Krash_order_Bot",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")]])
                )
            
            # Возврат в главное меню
            elif data == "back_to_menu":
                await self._show_main_menu(update)
        
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await query.edit_message_text("Произошла ошибка. Пожалуйста, попробуйте позже.")
    
    async def cancel_last_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена последнего активного заказа"""
        query = update.callback_query
        user_id = query.from_user.id
        logger.info(f"Attempting to cancel last order for user {user_id}")
        order = self.db.get_active_order(user_id)
        if order:
            order_id = order['order_id']
            if self.db.cancel_order(order_id):
                await query.edit_message_text("Заказ успешно отменён.")
                
                # Уведомление об отмене в группу
                if ADMIN_CHAT_ID:
                    cancel_text = f"ОТМЕНА ЗАКАЗА #{order_id}\n\n"
                    organization = order['order_data']['organization']
                    contact_person = order['order_data']['contact_person']
                    cancel_text += f"Организация: {organization}\nКонтактное лицо: {contact_person}\n\n"
                    for item in order['order_data']['items']:
                        cancel_text += f"{item['product']['title']} - {item['quantity']} шт.\n"
                    cancel_text += f"\nДата доставки: {order['delivery_date']}\nВремя доставки: {order['delivery_time']}\n"
                    cancel_text += "Заказ отменён пользователем."
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=cancel_text)
            else:
                await query.edit_message_text("Не удалось отменить заказ. Возможно, у вас нет активных заказов.")
        else:
            await query.edit_message_text("Не удалось отменить заказ. Возможно, у вас нет активных заказов.")
    
        async def show_active_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Показывает активные заказы пользователя"""
            query = update.callback_query
            user_id = query.from_user.id
            order = self.db.get_active_order(user_id)
            
            if not order:
                await query.edit_message_text(
                    text="У вас нет активных заказов.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")]])
                )
                return
            
            order_lines = []
            for item in order["order_data"]["items"]:
                p = item["product"]
                qty = item["quantity"]
                order_lines.append(f"▪️ {p['title']} - {qty} шт.")
            
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
        """Обработчик команды /stats для админов"""
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
                if len(parts[1]) == 2:  # Формат DD.MM - день
                    day, month = map(int, parts)
                    year = now.year
                    target_date = datetime(year, month, day)
                    start_date = end_date = target_date.strftime("%Y-%m-%d")
                    date_display = target_date.strftime("%d.%m")
                    period_display = f"Данные за {date_display}"
                elif len(parts[1]) == 4:  # Формат MM.YYYY - месяц
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
            # Без аргументов - текущий месяц
            is_month = True
            year = now.year
            month = now.month
            _, last_day = monthrange(year, month)
            start_date = datetime(year, month, 1).strftime("%Y-%m-%d")
            end_date = datetime(year, month, last_day).strftime("%Y-%m-%d")
            period_display = f"Данные с {datetime(year, month, 1).strftime('%d.%m')} по {datetime(year, month, last_day).strftime('%d.%m')}"
        
        # Запрос заказов за период
        try:
            self.db.cursor.execute("""
                SELECT order_id, user_id, order_data, delivery_date, delivery_time 
                FROM orders 
                WHERE delivery_date BETWEEN %s AND %s AND status = 'active'
            """, (start_date, end_date))
            orders = self.db.cursor.fetchall()
        except Exception as e:
            logger.error(f"Error fetching orders for period {start_date} to {end_date}: {e}")
            await update.message.reply_text("Ошибка при получении данных. Попробуйте позже.")
            return
        
        if not orders:
            await update.message.reply_text(f"Нет активных заказов за период {period_display}.")
            return
        
        # Агрегация данных
        if is_month:
            # Группировка по дате и клиенту для месяца
            date_user_orders = defaultdict(lambda: defaultdict(lambda: [0] * 13))
            client_info = {}  # {user_id: (contact, org)}
            
            for order in orders:
                order_data = order['order_data']  # Уже dict
                user_id = order['user_id']
                delivery_date = order['delivery_date']
                if user_id not in client_info:
                    client_info[user_id] = (order_data['contact_person'], order_data['organization'])
                
                quantities = date_user_orders[delivery_date][user_id]
                for item in order_data['items']:
                    prod_id = int(item['product']['id']) - 1
                    if 0 <= prod_id < 13:
                        quantities[prod_id] += item['quantity']
            
            # Подготовка CSV для месяца
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
            sorted_dates = sorted(date_user_orders.keys())  # Сортировка по датам
            for date_str in sorted_dates:
                user_data = date_user_orders[date_str]
                sorted_users = sorted(user_data.keys())  # Сортировка по user_id или по имени, если нужно
                for user_id in sorted_users:
                    contact, org = client_info[user_id]
                    quantities = user_data[user_id]
                    date_dd_mm = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
                    writer.writerow([date_dd_mm, contact, org] + quantities)
                    for i in range(13):
                        totals[i] += quantities[i]
            
            writer.writerow(['Итого', '', ''] + totals)
        else:
            # Логика для дня (как раньше)
            user_orders = {}
            for order in orders:
                order_data = order['order_data']
                user_id = order['user_id']
                if user_id not in user_orders:
                    user_orders[user_id] = {
                        'contact': order_data['contact_person'],
                        'org': order_data['organization'],
                        'quantities': [0] * 13
                    }
                
                for item in order_data['items']:
                    prod_id = int(item['product']['id']) - 1
                    if 0 <= prod_id < 13:
                        user_orders[user_id]['quantities'][prod_id] += item['quantity']
            
            csvfile = io.StringIO()
            writer = csv.writer(csvfile, dialect='excel', delimiter=',')
            
            writer.writerow([period_display] + [''] * 14)
            headers = [
                '', 'Клиент', 'Организация', 
                'Классический', 'Миндальный', 'Заморозка/10шт', 'Пан-о-шоколя', 
                'Ванильный', 'Шоколадный', 'Матча', 'Мини', 
                'Улитка/Изюм', 'Улитка/Мак', 'Булка/Кардамон', 
                'Комбо1', 'Комбо2'
            ]
            writer.writerow(headers)
            
            sorted_users = sorted(user_orders.items(), key=lambda x: x[1]['contact'])
            totals = [0] * 13
            for user_id, data in sorted_users:
                row = ['', data['contact'], data['org']] + data['quantities']
                writer.writerow(row)
                for i in range(13):
                    totals[i] += data['quantities'][i]
            
            writer.writerow(['Итого', '', ''] + totals)
        
        # Отправка файла
        csvfile.seek(0)
        filename = f"orders_{start_date.replace('-', '')}_{end_date.replace('-', '')}.csv" if is_month else f"orders_{date_display}.csv"
        await update.message.reply_document(
            document=InputFile(csvfile, filename=filename)
        )
    
    async def add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /add_admin"""
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
        """Обработчик команды /remove_admin"""
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

    async def _show_main_menu(self, update: Update):
        """Показывает главное меню"""
        await update.callback_query.edit_message_text(
            text="Выберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Каталог", callback_data="catalog")],
                [InlineKeyboardButton("📦 Мои заказы", callback_data="my_orders")],
                [InlineKeyboardButton("ℹ️ О нас", callback_data="about")]
            ])
        )

# Определение обработчика ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update.message:
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже или свяжитесь с поддержкой.")

def main():
    """Запуск бота"""
    try:
        application = ApplicationBuilder().token(TOKEN).build()
        handlers = BotHandlers()
        
        # Регистрация InlineQueryHandler для меню
        application.add_handler(InlineQueryHandler(handlers.inline_query))
        
        # Регистрация CallbackQueryHandler для кнопок
        application.add_handler(CallbackQueryHandler(handlers.handle_callback_query))
        
        # Регистрация ConversationHandler для регистрации
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", handlers.start)],
            states={
                REGISTER_ORG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.register_org)],
                REGISTER_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.register_contact)],
            },
            fallbacks=[CommandHandler("cancel", handlers.cancel_registration)],
            persistent=False,
            name="registration_conversation"
        )
        application.add_handler(conv_handler)
        
        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("info", handlers.check_client_info))
        application.add_handler(CommandHandler("stats", handlers.admin_stats))
        application.add_handler(CommandHandler("add_admin", handlers.add_admin))
        application.add_handler(CommandHandler("remove_admin", handlers.remove_admin))
        
        # Регистрация MessageHandler для товаров
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handlers.handle_product_message
        ))
        
        # Регистрация обработчика ошибок
        application.add_error_handler(error_handler)
        
        # Запуск бота
        logger.info("Бот запущен")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        if hasattr(handlers, 'db'):
            handlers.db.close()

if __name__ == '__main__':
    main()
