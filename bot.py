import os
import logging
from typing import Dict, Any, Optional, Tuple, List
import json
from datetime import datetime, timedelta, time
import psycopg2
from psycopg2 import extras, sql
from urllib.parse import urlparse
import io
import csv
from telegram import InputFile

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
    ConversationHandler,
    ApplicationBuilder
)

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
SECOND_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
MAX_ORDER_CANCEL_HOURS = 6

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

class DatabaseManager:
    """Класс для управления PostgreSQL базой данных"""
    
    def __init__(self):
        self.conn = self._connect()
        self._init_db()
        
    def _connect(self):
        """Устанавливает соединение с PostgreSQL"""
        try:
            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                raise ValueError("DATABASE_URL environment variable is not set")
                
            result = urlparse(db_url)
            self.conn = psycopg2.connect(
                dbname=result.path[1:],
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port,
                sslmode="require"
            )
            logger.info("Connected to PostgreSQL database")
            return self.conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise

    def _init_db(self):
        """Инициализация структуры базы данных"""
        try:
            with self.conn.cursor() as cursor:
                # Таблица клиентов
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS clients (
                        user_id BIGINT PRIMARY KEY,
                        organization TEXT NOT NULL,
                        contact_person TEXT,
                        username TEXT,
                        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Таблица корзин
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS carts (
                        user_id BIGINT PRIMARY KEY REFERENCES clients(user_id),
                        cart_data JSONB
                    )
                ''')
                
                # Таблица заказов
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS orders (
                        order_id SERIAL PRIMARY KEY,
                        user_id BIGINT REFERENCES clients(user_id),
                        order_data JSONB,
                        delivery_date TEXT,
                        delivery_time TEXT,
                        status TEXT DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица администраторов
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS admins (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                self.conn.commit()
                logger.info("Database tables initialized successfully")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Database initialization error: {e}")
            raise

    def save_client(self, user_id: int, organization: str, contact_person: str, username: str = None) -> None:
        """Сохраняет данные клиента в базу"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO clients (user_id, organization, contact_person, username)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        organization = EXCLUDED.organization,
                        contact_person = EXCLUDED.contact_person,
                        username = EXCLUDED.username
                ''', (user_id, organization, contact_person, username))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error saving client {user_id}: {e}")
            raise

    def get_client(self, user_id: int) -> Tuple[Optional[str], Optional[str]]:
        """Получает данные клиента из базы"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('''
                    SELECT organization, contact_person 
                    FROM clients 
                    WHERE user_id = %s
                ''', (user_id,))
                result = cursor.fetchone()
                return result if result else (None, None)
        except Exception as e:
            logger.error(f"Error getting client {user_id}: {e}")
            return None, None

    def save_cart(self, user_id: int, cart_data: Dict[str, Any]) -> None:
        """Сохраняет корзину пользователя"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO carts (user_id, cart_data)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        cart_data = EXCLUDED.cart_data
                ''', (user_id, json.dumps(cart_data)))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error saving cart for user {user_id}: {e}")
            raise

    def get_cart(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получает корзину пользователя"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('''
                    SELECT cart_data FROM carts WHERE user_id = %s
                ''', (user_id,))
                result = cursor.fetchone()
                return json.loads(result[0]) if result else None
        except Exception as e:
            logger.error(f"Error getting cart for user {user_id}: {e}")
            return None

    def save_order(self, user_id: int, order_data: Dict[str, Any], 
                  delivery_date: str, delivery_time: str) -> int:
        """Сохраняет заказ в базу и возвращает ID заказа"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO orders (user_id, order_data, delivery_date, delivery_time)
                    VALUES (%s, %s, %s, %s)
                    RETURNING order_id
                ''', (user_id, json.dumps(order_data), delivery_date, delivery_time))
                order_id = cursor.fetchone()[0]
                self.conn.commit()
                return order_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error saving order for user {user_id}: {e}")
            raise

    def cancel_order(self, order_id: int) -> bool:
        """Отменяет заказ"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('''
                    UPDATE orders 
                    SET status = 'cancelled' 
                    WHERE order_id = %s AND status = 'active'
                ''', (order_id,))
                rows_affected = cursor.rowcount
                self.conn.commit()
                return rows_affected > 0
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    def get_active_order(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получает активный заказ пользователя"""
        try:
            with self.conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                    SELECT order_id, order_data, delivery_date, delivery_time 
                    FROM orders 
                    WHERE user_id = %s AND status = 'active'
                    ORDER BY created_at DESC 
                    LIMIT 1
                ''', (user_id,))
                result = cursor.fetchone()
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

    def close(self):
        """Закрывает соединение с базой данных"""
        if self.conn and not self.conn.closed:
            self.conn.close()
            logger.info("Database connection closed")
    
    def get_monthly_croissant_stats(self, start_date: str, end_date: str) -> List[Dict]:
        """Возвращает статистику по круассантам за период с временными промежутками"""
        try:
            with self.conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                    SELECT 
                        c.organization AS "Клиент",
                        o.delivery_date AS "Дата доставки",
                        o.delivery_time AS "Временной промежуток",
                        SUM(CASE WHEN (o.order_data->>'product_type') = 'classic' THEN (o.order_data->>'quantity')::INT ELSE 0 END) AS "Классические",
                        SUM(CASE WHEN (o.order_data->>'product_type') = 'chocolate' THEN (o.order_data->>'quantity')::INT ELSE 0 END) AS "Шоколадные",
                        SUM(CASE WHEN (o.order_data->>'product_type') = 'mini' THEN (o.order_data->>'quantity')::INT ELSE 0 END) AS "Мини",
                        SUM((o.order_data->>'quantity')::INT) AS "Итого"
                    FROM 
                        clients c
                    JOIN 
                        orders o ON c.user_id = o.user_id
                    WHERE 
                        o.created_at BETWEEN %s AND %s
                        AND o.status = 'active'
                    GROUP BY 
                        c.organization, o.delivery_date, o.delivery_time
                    ORDER BY 
                        c.organization, o.delivery_date, o.delivery_time;
                ''', (start_date, end_date))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting monthly stats: {e}")
            return []
        
    def add_admin(self, user_id: int, username: str = None) -> bool:
        """Добавляет администратора"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO admins (user_id, username)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO NOTHING
            ''', (user_id, username))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error adding admin {user_id}: {e}")
            return False

    def remove_admin(self, user_id: int) -> bool:
        """Удаляет администратора"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('DELETE FROM admins WHERE user_id = %s', (user_id,))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error removing admin {user_id}: {e}")
            return False

    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute('SELECT 1 FROM admins WHERE user_id = %s', (user_id,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking admin {user_id}: {e}")
            return False

class BotHandlers:
    """Класс для обработчиков бота"""
    
    def __init__(self):
        self.user_carts = {}  # Временное хранилище корзин
        self.current_editing = {}  # Текущий редактируемый товар
        self.selected_dates = {}  # Выбранные даты доставки
        self.last_orders = {}  # Последние заказы пользователей
        self.db = DatabaseManager()

    async def _show_main_menu(self, update: Update):
        """Показывает главное меню"""
        keyboard = [
            [InlineKeyboardButton("🛒 Каталог", callback_data="catalog")],
            [InlineKeyboardButton("📦 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton("ℹ️ О нас", callback_data="about")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🏠 Главное меню",
            reply_markup=reply_markup
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        try:
            user = update.message.from_user
            organization, contact_person = self.db.get_client(user.id)
            
            if organization:
                await update.message.reply_text(
                    "Меню товаров:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("Открыть меню", switch_inline_query_current_chat="")
                    ]])
                )
            else:
                await update.message.reply_text(
                    "Добро пожаловать! Для начала работы необходимо зарегистрироваться.\n"
                    "Пожалуйста, введите название вашей организации:"
                )
                return REGISTER_ORG
        except Exception as e:
            logger.error(f"Error in start: {e}")
            await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже.")
            return ConversationHandler.END

    async def register_org(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ввода организации"""
        try:
            context.user_data['organization'] = update.message.text
            await update.message.reply_text("Теперь введите ваше контактное лицо (ФИО):")
            return REGISTER_CONTACT
        except Exception as e:
            logger.error(f"Error in register_org: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "Произошла ошибка при обработке названия организации. "
                "Пожалуйста, попробуйте снова или обратитесь в поддержку."
            )
            return REGISTER_ORG

    async def register_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ввода контактного лица"""
        try:
            user = update.message.from_user
            organization = context.user_data.get('organization')
            
            if not organization:
                await update.message.reply_text("Сначала введите название организации через /start")
                return REGISTER_ORG
                
            contact_person = update.message.text
            
            # Сохраняем данные в PostgreSQL
            self.db.save_client(
                user_id=user.id,
                organization=organization,
                contact_person=contact_person,
                username=user.username
            )
            
            logger.info(f"New user registered: {user.id} - {organization}")
            
            # Отправляем подтверждение
            await update.message.reply_text(
                "✅ Регистрация завершена!\n\n"
                f"🏢 Организация: {organization}\n"
                f"👤 Контактное лицо: {contact_person}\n\n"
                "Теперь вы можете делать заказы!"
            )
            
            await update.message.reply_text(
                "Меню товаров:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Открыть меню", switch_inline_query_current_chat="")
                ]])
            )
            return ConversationHandler.END
            
        except psycopg2.Error as e:
            logger.error(f"Database error in register_contact: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "Ошибка сохранения данных. Пожалуйста, попробуйте позже."
            )
            return REGISTER_CONTACT
        except Exception as e:
            logger.error(f"Unexpected error in register_contact: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "Произошла непредвиденная ошибка. Пожалуйста, попробуйте снова."
            )
            return REGISTER_CONTACT

    async def cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена регистрации"""
        try:
            # Очищаем временные данные
            if 'organization' in context.user_data:
                del context.user_data['organization']
                
            await update.message.reply_text(
                "Регистрация отменена.\n"
                "Вы можете начать заново с помощью команды /start"
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in cancel_registration: {str(e)}", exc_info=True)
            await update.message.reply_text("Произошла ошибка при отмене регистрации.")
            return ConversationHandler.END

    async def check_client_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает информацию о клиенте"""
        try:
            user_id = update.message.from_user.id
            organization, contact_person = self.db.get_client(user_id)
            
            if organization:
                await update.message.reply_text(
                    "📋 Ваши регистрационные данные:\n\n"
                    f"🏢 Организация: {organization}\n"
                    f"👤 Контактное лицо: {contact_person}\n\n"
                    "Для изменения данных обратитесь к менеджеру."
                )
            else:
                await update.message.reply_text(
                    "Вы еще не зарегистрированы!\n"
                    "Для регистрации используйте команду /start"
                )
        except psycopg2.Error as e:
            logger.error(f"Database error in check_client_info: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "Ошибка получения данных. Пожалуйста, попробуйте позже."
            )
        except Exception as e:
            logger.error(f"Unexpected error in check_client_info: {str(e)}", exc_info=True)
            await update.message.reply_text("Произошла непредвиденная ошибка.")

    async def inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик inline запросов"""
        query = update.inline_query.query
        results = []
        
        for product in PRODUCTS:
            if query.lower() in product["title"].lower():
                results.append(
                    InlineQueryResultArticle(
                        id=product["id"],
                        title=product["title"],
                        description=product["description"],
                        thumb_url=product["thumb_url"],
                        input_message_content=InputTextMessageContent(
                            f"{product['title']}\n{product['description']}"
                        )
                    )
                )
        
        await update.inline_query.answer(results)

    async def handle_product_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик сообщений с товарами"""
        await update.message.delete()
        message_text = update.message.text
        first_line = message_text.split('\n', 1)[0].strip()
        
        if (product := PRODUCTS_BY_TITLE.get(first_line)):
            user_id = update.message.from_user.id
            
            if user_id not in self.user_carts:
                self.user_carts[user_id] = {"items": []}
            
            cart = self.user_carts[user_id]["items"]
            for item in cart:
                if item["product"]["id"] == product["id"]:
                    item["quantity"] += 1
                    break
            else:
                cart.append({"product": product, "quantity": 1})
            
            self.current_editing[user_id] = len(cart) - 1
            await self.show_cart(update, user_id)

    async def show_cart(self, update: Update, user_id: int, edit_message: bool = False):
        """Показывает корзину пользователя"""
        if not self.user_carts.get(user_id, {}).get("items"):
            return
        
        cart = self.user_carts[user_id]["items"]
        editing_index = self.current_editing.get(user_id, 0)
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
        
        # Генерация клавиатуры
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

    async def show_delivery_dates(self, update: Update, user_id: int):
        """Показывает доступные даты доставки"""
        DELIVERY_DATES, DATE_KEYS = generate_delivery_dates()
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

    async def show_delivery_times(self, update: Update, user_id: int):
        """Показывает доступные интервалы доставки"""
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

    async def process_delivery_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает выбор времени доставки и оформляет заказ"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        user_id = user.id
        time_str = query.data.split("_", 2)[-1]
        date_str = self.selected_dates.get(user_id)
        
        if not date_str:
            await query.answer("Ошибка: дата не выбрана")
            return
        
        # Проверяем регистрацию клиента
        organization, contact_person = self.db.get_client(user.id)
        if not organization:
            await query.edit_message_text(
                "Перед оформлением заказа необходимо зарегистрироваться!\n"
                "Используйте команду /start"
            )
            return
        
        # Формирование информации о заказе
        cart = self.user_carts[user_id]["items"]
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
        
        # Сохраняем заказ в базу данных
        order_data = {
            "items": [{
                "product": item["product"],
                "quantity": item["quantity"]
            } for item in cart],
            "organization": organization,
            "contact_person": contact_person,
            "username": user.username
        }
        
        order_id = self.db.save_order(
            user_id=user_id,
            order_data=order_data,
            delivery_date=date_str,
            delivery_time=time_str
        )
        
        # Сохраняем заказ для возможной отмены
        self.last_orders[user_id] = {
            "order_id": order_id,
            "order_text": order_text,
            "delivery_datetime": delivery_datetime
        }
        
        # Добавляем кнопку отмены заказа
        keyboard = [
            [InlineKeyboardButton("❌ Отменить заказ", callback_data="cancel_last_order")],
            [InlineKeyboardButton("👨‍💼 Связаться с менеджером", url="https://t.me/Krash_order_Bot")]
        ]
        
        # Проверяем, осталось ли до доставки больше 6 часов
        time_left = delivery_datetime - datetime.now()
        if time_left <= timedelta(hours=6):
            order_text += "\n\n⚠️ Отмена заказа возможна не позднее чем за 6 часов до доставки. Сейчас отменить заказ уже нельзя."
            keyboard = [[InlineKeyboardButton("👨‍💼 Связаться с менеджером", url="https://t.me/Krash_order_Bot")]]
        
        await query.edit_message_text(
            text=order_text + "\nДля уточнения деталей с вами свяжется менеджер.",
            reply_markup=InlineKeyboardMarkup(keyboard))
        
        # Уведомление в группу
        admin_message = (
            f"=== НОВЫЙ ЗАКАЗ ===\n\n"
            f"🏢 Организация: {organization}\n"
            f"👤 Контакт: {contact_person}\n"
            f"📱 Телеграм: @{user.username if user.username else 'не указан'}\n"
            f"📅 Доставка: {delivery_date.strftime('%d.%m.%Y')} {time_str}\n"
            f"🆔 Номер заказа: {order_id}\n\n"
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
            self.last_orders[user_id]["admin_message_id"] = sent_message.message_id
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления: {e}")
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ Произошла ошибка при обработке заказа. Пожалуйста, свяжитесь с @Krash_order_Bot"
            )
        
        # Очистка данных
        self.user_carts[user_id] = {"items": []}
        self.selected_dates.pop(user_id, None)

    async def cancel_last_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает отмену заказа"""
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
            # Убираем первую строку из оригинального сообщения
            order_text = "\n".join(order_data["order_text"].split("\n")[1:])
            await query.edit_message_text(
                text="⚠️ Отмена заказа возможна не позднее чем за 6 часов до доставки. Сейчас отменить заказ уже нельзя.\n\n" + 
                     order_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👨‍💼 Связаться с менеджером", url="https://t.me/Krash_order_Bot")]
                ])
            )
            return
        
        # Отменяем заказ в базе данных
        if not self.db.cancel_order(order_data["order_id"]):
            await query.edit_message_text(text="Не удалось отменить заказ. Пожалуйста, свяжитесь с менеджером.")
            return
        
        # Уведомляем группу об отмене заказа
        try:
            admin_message = (
                f"=== ЗАКАЗ ОТМЕНЕН ===\n\n"
                f"👤 Клиент: {query.from_user.full_name}\n"
                f"📱 Телеграм: @{query.from_user.username if query.from_user.username else 'не указан'}\n"
                f"🆔 Номер заказа: {order_data['order_id']}\n\n"
                f"Заказ отменен пользователем."
            )
            
            await context.bot.send_message(
                chat_id=SECOND_CHAT_ID,
                text=admin_message,
                reply_to_message_id=order_data.get("admin_message_id"),
                disable_notification=True
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об отмене: {e}")
        
        # Удаляем заказ из истории
        del self.last_orders[user_id]
        
        # Убираем первую строку из оригинального сообщения
        order_text = "\n".join(order_data["order_text"].split("\n")[1:])
        
        await query.edit_message_text(
            text="❌ Ваш заказ был отменен.\n\n" + order_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Сделать новый заказ", switch_inline_query_current_chat="")]
            ])
        )

    async def handle_quantity_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопок выбора количества и навигации"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        data = query.data
        
        if data == "cancel_last_order":
            await self.cancel_last_order(update, context)
            return
            
        if not self.user_carts.get(user_id, {}).get("items"):
            await query.edit_message_text(text="Ваша корзина пуста!")
            return
        
        if data == "select_delivery_date":
            await self.show_delivery_dates(update, user_id)
            return
            
        elif data.startswith("delivery_date_"):
            self.selected_dates[user_id] = data.split("_", 2)[-1]
            await self.show_delivery_times(update, user_id)
            return
            
        elif data.startswith("delivery_time_"):
            await self.process_delivery_time(update, context)
            return
            
        elif data == "back_to_cart":
            await self.show_cart(update, user_id,)
            return
            
        elif data == "back_to_dates":
            await self.show_delivery_dates(update, user_id)
            return
            
        cart = self.user_carts[user_id]["items"]
        editing_index = self.current_editing.get(user_id, 0)
        
        if data == "prev_item":
            new_index = max(0, editing_index - 1)
            self.current_editing[user_id] = new_index
            await self.show_cart(update, user_id, edit_message=True)
            
        elif data == "next_item":
            new_index = min(len(cart) - 1, editing_index + 1)
            self.current_editing[user_id] = new_index
            await self.show_cart(update, user_id, edit_message=True)
            
        elif data == "increase":
            cart[editing_index]["quantity"] += 1
            await self.show_cart(update, user_id, edit_message=True)
            
        elif data == "decrease":
            if cart[editing_index]["quantity"] > 1:
                cart[editing_index]["quantity"] -= 1
                await self.show_cart(update, user_id, edit_message=True)
                
        elif data == "remove_item":
            cart.pop(editing_index)
            if editing_index >= len(cart) and len(cart) > 0:
                self.current_editing[user_id] = len(cart) - 1
                
            if len(cart) == 0:
                await query.edit_message_text(text="Ваша корзина пуста!")
                del self.user_carts[user_id]
            else:
                await self.show_cart(update, user_id, edit_message=True)

    async def show_my_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает активные заказы пользователя"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        active_order = self.db.get_active_order(user_id)
        if not active_order:
            await query.edit_message_text(
                text="У вас нет активных заказов.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Сделать заказ", switch_inline_query_current_chat="")]
                ])
            )
            return
            
        # Формируем текст заказа
        order_lines = []
        for item in active_order['order_data']['items']:
            p = item['product']
            qty = item['quantity']
            order_lines.append(f"▪️ {p['title']} - {qty} шт.")
            
        order_text = (
            f"📦 Ваш активный заказ:\n\n" +
            "\n".join(order_lines) + "\n\n" +
            f"📅 Дата доставки: {active_order['delivery_date']}\n" +
            f"🕒 Время доставки: {active_order['delivery_time']}\n"
        )
        
        # Проверяем, можно ли еще отменить заказ
        delivery_date = datetime.strptime(active_order['delivery_date'], "%Y-%m-%d")
        delivery_time = active_order['delivery_time'].split(" - ")[0]
        delivery_datetime = datetime.strptime(f"{active_order['delivery_date']} {delivery_time}", "%Y-%m-%d %H:%M")
        time_left = delivery_datetime - datetime.now()
        
        keyboard = []
        if time_left > timedelta(hours=6):
            keyboard.append([InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_order_{active_order['order_id']}")])
        keyboard.append([InlineKeyboardButton("👨‍💼 Связаться с менеджером", url="https://t.me/Krash_order_Bot")])
        
        await query.edit_message_text(
            text=order_text,
            reply_markup=InlineKeyboardMarkup(keyboard))
            
    async def cancel_order_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает отмену заказа из меню 'Мои заказы'"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        order_id = int(query.data.split("_")[-1])
        
        # Отменяем заказ в базе данных
        if not self.db.cancel_order(order_id):
            await query.edit_message_text(text="Не удалось отменить заказ. Пожалуйста, свяжитесь с менеджером.")
            return
            
        # Уведомляем группу об отмене заказа
        try:
            admin_message = (
                f"=== ЗАКАЗ ОТМЕНЕН ===\n\n"
                f"👤 Клиент: {query.from_user.full_name}\n"
                f"📱 Телеграм: @{query.from_user.username if query.from_user.username else 'не указан'}\n"
                f"🆔 Номер заказа: {order_id}\n\n"
                f"Заказ отменен пользователем."
            )
            
            await context.bot.send_message(
                chat_id=SECOND_CHAT_ID,
                text=admin_message,
                disable_notification=True
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об отмене: {e}")
            
        await query.edit_message_text(
            text="❌ Ваш заказ был отменен.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Сделать новый заказ", switch_inline_query_current_chat="")]
            ])
        )

    async def show_about(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает информацию о компании"""
        query = update.callback_query
        await query.answer()
        
        about_text = (
            "🏢 О компании Krash:\n\n"
            "Мы производим свежую и вкусную выпечку каждый день!\n\n"
            "📍 Наш адрес: г. Москва, ул. Примерная, 123\n"
            "📞 Телефон: +7 (123) 456-78-90\n"
            "🕒 Часы работы: 6:00 - 18:00\n\n"
            "Для связи с менеджером: @Krash_order_Bot"
        )
        
        await query.edit_message_text(
            text=about_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
            ])
        )

    async def back_to_main(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Возвращает в главное меню"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🛒 Каталог", callback_data="catalog")],
            [InlineKeyboardButton("📦 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton("ℹ️ О нас", callback_data="about")],
        ]
        
        await query.edit_message_text(
            text="🏠 Главное меню",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def generate_monthly_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Генерирует месячный отчет по заказам (только для админов)"""
        if not self.db.is_admin(update.message.from_user.id):
            await update.message.reply_text("Эта команда доступна только администраторам.")
            return

            
        try:
            # Получаем даты начала и конца месяца
            today = datetime.now()
            first_day = today.replace(day=1)
            last_day = (first_day + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            # Получаем статистику из базы данных
            stats = self.db.get_monthly_croissant_stats(
                first_day.strftime("%Y-%m-%d"),
                last_day.strftime("%Y-%m-%d")
            )
            
            if not stats:
                await update.message.reply_text("Нет данных для отчета за текущий месяц.")
                return
                
            # Создаем CSV файл
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=stats[0].keys())
            writer.writeheader()
            writer.writerows(stats)
            
            # Отправляем файл
            output.seek(0)
            await update.message.reply_document(
                document=InputFile(io.BytesIO(output.getvalue().encode()), filename="monthly_report.csv"),
                caption=f"Отчет за период с {first_day.strftime('%d.%m.%Y')} по {last_day.strftime('%d.%m.%Y')}"
            )
        except Exception as e:
            logger.error(f"Error generating monthly report: {e}")
            await update.message.reply_text("Произошла ошибка при генерации отчета.")
    
    async def add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Добавляет администратора (только для владельца)"""
        user = update.message.from_user
        if user.id != SECOND_CHAT_ID:  # SECOND_CHAT_ID - это ID главного администратора
            await update.message.reply_text("Эта команда доступна только владельцу бота.")
            return

        try:
            target_user = update.message.reply_to_message.from_user
            if self.db.add_admin(target_user.id, target_user.username):
                await update.message.reply_text(f"Пользователь @{target_user.username} добавлен в администраторы.")
            else:
                await update.message.reply_text("Не удалось добавить администратора или он уже был добавлен.")
        except Exception as e:
            logger.error(f"Error in add_admin: {e}")
            await update.message.reply_text("Ошибка при добавлении администратора.")

    async def remove_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удаляет администратора (только для владельца)"""
        user = update.message.from_user
        if user.id != SECOND_CHAT_ID:
            await update.message.reply_text("Эта команда доступна только владельцу бота.")
            return

        try:
            target_user = update.message.reply_to_message.from_user
            if self.db.remove_admin(target_user.id):
                await update.message.reply_text(f"Пользователь @{target_user.username} удален из администраторов.")
            else:
                await update.message.reply_text("Не удалось удалить администратора или он не был найден.")
        except Exception as e:
            logger.error(f"Error in remove_admin: {e}")
            await update.message.reply_text("Ошибка при удалении администратора.")

    async def list_admins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает список администраторов"""
        try:
            with self.db.conn.cursor() as cursor:
                cursor.execute('SELECT user_id, username FROM admins ORDER BY added_at')
                admins = cursor.fetchall()

            if not admins:
                await update.message.reply_text("Нет администраторов.")
                return

            admin_list = "\n".join([f"@{admin[1] or 'unknown'} (ID: {admin[0]})" for admin in admins])
            await update.message.reply_text(f"Список администраторов:\n\n{admin_list}")
        except Exception as e:
            logger.error(f"Error in list_admins: {e}")
            await update.message.reply_text("Ошибка при получении списка администраторов.")        

def main():
    """Запуск бота"""
    try:
        # Инициализация бота
        application = ApplicationBuilder().token(TOKEN).build()
        handlers = BotHandlers()

        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("start", handlers.start))
        application.add_handler(CommandHandler("info", handlers.check_client_info))
        application.add_handler(CommandHandler("report", handlers.generate_monthly_report))
        
        # Регистрация обработчиков сообщений
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            handlers.handle_product_message))
            
        # Регистрация inline обработчиков
        application.add_handler(InlineQueryHandler(handlers.inline_query))
        
        # Регистрация обработчиков команд для администрирования
        application.add_handler(CommandHandler("addadmin", handlers.add_admin))
        application.add_handler(CommandHandler("removeadmin", handlers.remove_admin))
        application.add_handler(CommandHandler("listadmins", handlers.list_admins))

        # Регистрация обработчиков кнопок
        application.add_handler(CallbackQueryHandler(
            handlers.handle_quantity_buttons,
            pattern="^(prev_item|next_item|increase|decrease|remove_item|select_delivery_date|delivery_date_.*|delivery_time_.*|back_to_cart|back_to_dates|cancel_last_order|cancel_order_.*)$"))
            
        application.add_handler(CallbackQueryHandler(
            handlers.show_my_orders,
            pattern="^my_orders$"))
            
        application.add_handler(CallbackQueryHandler(
            handlers.show_about,
            pattern="^about$"))
            
        application.add_handler(CallbackQueryHandler(
            handlers.back_to_main,
            pattern="^back_to_main$"))
            
        # Регистрация ConversationHandler для регистрации
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", handlers.start)],
            states={
                REGISTER_ORG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.register_org)],
                REGISTER_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.register_contact)],
            },
            fallbacks=[CommandHandler("cancel", handlers.cancel_registration)],
        )
        application.add_handler(conv_handler)
        
        # Запуск бота
        logger.info("Bot is starting...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
    finally:
        if hasattr(handlers, 'db'):
            handlers.db.close()

if __name__ == "__main__":
    main()
