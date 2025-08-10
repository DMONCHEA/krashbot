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
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_CHAT_ID", "").split(",") if id.strip() and id.strip().isdigit()]
MAX_ORDER_CANCEL_HOURS = 6

# Добавим логирование для проверки ADMIN_IDS
logger.info(f"Initialized with ADMIN_IDS: {ADMIN_IDS}")

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
            conn = psycopg2.connect(
                dbname=result.path[1:],
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port,
                sslmode="require"
            )
            logger.info("Connected to PostgreSQL database")
            return conn
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
                return ConversationHandler.END
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
        try:
            await update.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

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
            if edit_message:
                await update.callback_query.edit_message_text(text="Ваша корзина пуста!")
            else:
                await update.message.reply_text("Ваша корзина пуста!")
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
        if not cart:
            await query.edit_message_text("Ваша корзина пуста!")
            return
            
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
        
        try:
            order_id = self.db.save_order(
                user_id=user_id,
                order_data=order_data,
                delivery_date=date_str,
                delivery_time=time_str
            )
            logger.info(f"Order #{order_id} saved successfully for user {user_id}")
        except Exception as e:
            logger.error(f"Error saving order: {e}")
            await query.edit_message_text(
                "Произошла ошибка при сохранении заказа. Пожалуйста, попробуйте позже."
            )
            return
        
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
        
        # Уведомление в группу (если ADMIN_IDS не пуст)
        if ADMIN_IDS:
            admin_message = (
                f"=== НОВЫЙ ЗАКАЗ ===\n\n"
                f"🏢 Организация: {organization}\n"
                f"👤 Контакт: {contact_person}\n"
                f"📱 Телеграм: @{user.username if user.username else 'не указан'}\n"
                f"📅 Доставка: {delivery_date.strftime('%d.%m.%Y')} {time_str}\n"
                f"🆔 Номер заказа: {order_id}\n\n"
                "Состав заказа:\n" + "\n".join(order_lines)
            )

        for admin_id in ADMIN_IDS:
            try:
                kb = [[InlineKeyboardButton("📨 Написать клиенту", url=f"https://t.me/{user.username}")]] if user.username else None
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    reply_markup=InlineKeyboardMarkup(kb) if kb else None,
                    disable_notification=True
                )
                logger.info(f"Уведомление отправлено в чат {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки в чат {admin_id}: {e}")
        else:
            logger.error("Не удалось отправить уведомление: ADMIN_IDS пуст!")
        
        # Добавим логирование перед отправкой
        logger.info(f"Attempting to send order notification to ADMIN_IDS: {ADMIN_IDS}")
        
        if not ADMIN_IDS:
            logger.error("Cannot send notification - ADMIN_IDS is empty")
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ Произошла ошибка при обработке заказа. Пожалуйста, свяжитесь с @Krash_order_Bot"
            )
            return
            
        try:
            kb = [[InlineKeyboardButton("📨 Написать клиенту", url=f"https://t.me/{user.username}")]] if user.username else None
            for admin_id in ADMIN_IDS:
                try:
                    sent_message = await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        reply_markup=InlineKeyboardMarkup(kb) if kb else None,
                        disable_notification=True
                    )
                    logger.info(f"Notification sent successfully to {admin_id}")
                    if admin_id == ADMIN_IDS[0]:  # Сохраняем ID сообщения только для первого админа
                        self.last_orders[user_id]["admin_message_id"] = sent_message.message_id
                except Exception as e:
                    logger.error(f"Failed to send notification to {admin_id}: {e}")
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
        
        # Уведомляем администратора об отмене
        if "admin_message_id" in order_data:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_IDS[0],
                    text=f"⚠️ ЗАКАЗ ОТМЕНЕН ⚠️\n\n"
                         f"Заказ №{order_data['order_id']} был отменен клиентом.\n"
                         f"Оригинальное сообщение:\n\n{order_data['order_text']}",
                    reply_to_message_id=order_data["admin_message_id"]
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления об отмене: {e}")

        # Обновляем сообщение для пользователя
        await query.edit_message_text(
            text="❌ Ваш заказ был отменен.\n\n" + order_data["order_text"],
            reply_markup=None
        )
        
        # Удаляем информацию о заказе
        del self.last_orders[user_id]

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback запросов"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        try:
            # Обработка навигации по товарам в корзине
            if data == "prev_item":
                if user_id in self.current_editing:
                    cart = self.user_carts.get(user_id, {}).get("items", [])
                    if cart:
                        self.current_editing[user_id] = (self.current_editing[user_id] - 1) % len(cart)
                        await self.show_cart(update, user_id, edit_message=True)
            
            elif data == "next_item":
                if user_id in self.current_editing:
                    cart = self.user_carts.get(user_id, {}).get("items", [])
                    if cart:
                        self.current_editing[user_id] = (self.current_editing[user_id] + 1) % len(cart)
                        await self.show_cart(update, user_id, edit_message=True)
            
            # Обработка изменения количества товара
            elif data == "increase":
                if user_id in self.current_editing:
                    idx = self.current_editing[user_id]
                    if user_id in self.user_carts and idx < len(self.user_carts[user_id]["items"]):
                        self.user_carts[user_id]["items"][idx]["quantity"] += 1
                        await self.show_cart(update, user_id, edit_message=True)
            
            elif data == "decrease":
                if user_id in self.current_editing:
                    idx = self.current_editing[user_id]
                    if user_id in self.user_carts and idx < len(self.user_carts[user_id]["items"]):
                        if self.user_carts[user_id]["items"][idx]["quantity"] > 1:
                            self.user_carts[user_id]["items"][idx]["quantity"] -= 1
                            await self.show_cart(update, user_id, edit_message=True)
            
            # Удаление товара из корзины
            elif data == "remove_item":
                if user_id in self.current_editing:
                    idx = self.current_editing[user_id]
                    if user_id in self.user_carts and idx < len(self.user_carts[user_id]["items"]):
                        del self.user_carts[user_id]["items"][idx]
                        
                        # Обновляем индекс редактирования
                        if self.user_carts[user_id]["items"]:
                            self.current_editing[user_id] = min(idx, len(self.user_carts[user_id]["items"]) - 1)
                        else:
                            del self.current_editing[user_id]
                        
                        await self.show_cart(update, user_id, edit_message=True)
            
            # Выбор даты доставки
            elif data == "select_delivery_date":
                await self.show_delivery_dates(update, user_id)
            
            # Возврат в корзину
            elif data == "back_to_cart":
                await self.show_cart(update, user_id, edit_message=True)
            
            # Возврат к выбору даты
            elif data == "back_to_dates":
                await self.show_delivery_dates(update, user_id)
            
            # Обработка выбора даты доставки
            elif data.startswith("delivery_date_"):
                date_str = data.split("_", 2)[-1]
                self.selected_dates[user_id] = date_str
                await self.show_delivery_times(update, user_id)
            
            # Обработка выбора времени доставки
            elif data.startswith("delivery_time_"):
                await self.process_delivery_time(update, context)
            
            # Отмена последнего заказа
            elif data == "cancel_last_order":
                await self.cancel_last_order(update, context)
            
            # Просмотр активных заказов
            elif data == "my_orders":
                await self.show_active_orders(update, user_id)
            
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

    async def show_active_orders(self, update: Update, user_id: int):
        """Показывает активные заказы пользователя"""
        order = self.db.get_active_order(user_id)
        
        if not order:
            await update.callback_query.edit_message_text(
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
        
        await update.callback_query.edit_message_text(
            text=order_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет администратору статистику заказов"""
        if not self.db.is_admin(update.message.from_user.id):
            await update.message.reply_text("Эта команда доступна только администраторам.")
            return
        
        try:
            # Получаем статистику за текущий месяц
            today = datetime.now()
            first_day = today.replace(day=1)
            last_day = (first_day + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            stats = self.db.get_monthly_croissant_stats(
                first_day.strftime("%Y-%m-%d"),
                last_day.strftime("%Y-%m-%d")
            )
            
            if not stats:
                await update.message.reply_text("Нет данных о заказах за текущий месяц.")
                return
            
            # Формируем CSV файл
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=stats[0].keys())
            writer.writeheader()
            writer.writerows(stats)
            
            output.seek(0)
            await update.message.reply_document(
                document=InputFile(io.BytesIO(output.getvalue().encode()), filename="stats.csv"),
                caption=f"Статистика заказов с {first_day.strftime('%d.%m.%Y')} по {last_day.strftime('%d.%m.%Y')}"
            )
        except Exception as e:
            logger.error(f"Error generating stats: {e}")
            await update.message.reply_text("Произошла ошибка при формировании статистики.")

    async def add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Добавляет администратора"""
        user = update.message.from_user
        if user.id not in ADMIN_IDS:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return
            
        if not context.args:
            await update.message.reply_text("Использование: /add_admin <user_id>")
            return
            
        try:
            new_admin_id = int(context.args[0])
            if self.db.add_admin(new_admin_id):
                await update.message.reply_text(f"Пользователь {new_admin_id} добавлен как администратор.")
            else:
                await update.message.reply_text(f"Пользователь {new_admin_id} уже является администратором.")
        except ValueError:
            await update.message.reply_text("Некорректный ID пользователя.")

    async def remove_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удаляет администратора"""
        user = update.message.from_user
        if user.id not in ADMIN_IDS:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return
            
        if not context.args:
            await update.message.reply_text("Использование: /remove_admin <user_id>")
            return
            
        try:
            admin_id = int(context.args[0])
            if user.id == admin_id:
                await update.message.reply_text("Вы не можете удалить сами себя.")
                return
                
            if self.db.remove_admin(admin_id):
                await update.message.reply_text(f"Пользователь {admin_id} удален из администраторов.")
            else:
                await update.message.reply_text(f"Пользователь {admin_id} не является администратором.")
        except ValueError:
            await update.message.reply_text("Некорректный ID пользователя.")

def main():
    """Запуск бота"""
    try:
        # Инициализация бота
        application = ApplicationBuilder().token(TOKEN).build()
        handlers = BotHandlers()
        
        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("start", handlers.start))
        application.add_handler(CommandHandler("info", handlers.check_client_info))
        application.add_handler(CommandHandler("stats", handlers.admin_stats))
        application.add_handler(CommandHandler("add_admin", handlers.add_admin))
        application.add_handler(CommandHandler("remove_admin", handlers.remove_admin))
        
        # Регистрация обработчика inline запросов
        application.add_handler(InlineQueryHandler(handlers.inline_query))
        
        # Регистрация обработчика сообщений с товарами
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, handlers.handle_product_message
        ))
        
        # Регистрация обработчика callback запросов
        application.add_handler(CallbackQueryHandler(handlers.handle_callback_query))
        
        # Регистрация обработчика регистрации
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
        logger.info("Бот запущен")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        if hasattr(handlers, 'db'):
            handlers.db.close()

if __name__ == "__main__":
    main()
