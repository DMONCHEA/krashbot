import os
import logging
from typing import Dict, Any, Optional, Tuple, List
import json
from datetime import datetime, timedelta
import psycopg2
from psycopg2 import extras, sql
from urllib.parse import urlparse

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
SECOND_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
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

class BotHandlers:
    """Класс для обработчиков бота"""
    
    def __init__(self):
        self.user_carts = {}  # Временное хранилище корзин
        self.current_editing = {}  # Текущий редактируемый товар
        self.selected_dates = {}  # Выбранные даты доставки
        self.db = DatabaseManager()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        try:
            user = update.message.from_user
            organization, contact_person = self.db.get_client(user.id)
            
            if organization:
                await self._show_main_menu(update)
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
        
        await self._show_main_menu(update)
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

async def health_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка работоспособности бота"""
    try:
        # Проверка соединения с PostgreSQL
        with self.db.conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_status = "✅"
    except Exception as e:
        db_status = f"❌ (Ошибка: {str(e)})"
    
    try:
        user_count = self._get_user_count()
        active_carts = len(self.user_carts)
        
        await update.message.reply_text(
            "🛠 Статус системы:\n\n"
            f"🔹 База данных: {db_status}\n"
            f"🔹 Пользователей: {user_count}\n"
            f"🔹 Активных корзин: {active_carts}\n\n"
            "Бот работает в штатном режиме" if db_status == "✅" else "Имеются проблемы с БД"
        )
    except Exception as e:
        logger.error(f"Error in health_check: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Не удалось проверить статус системы. "
            "Пожалуйста, обратитесь к администратору."
        )

    def _get_user_count(self) -> int:
        """Возвращает количество зарегистрированных пользователей"""
        try:
            with self.db.conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM clients")
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error getting user count: {e}")
            return -1

    async def health_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка работоспособности бота"""
        try:
            # Проверка соединения с базой данных
            with self.db.conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            
            await update.message.reply_text(
                "✅ Бот работает нормально\n"
                f"📊 Пользователей: {self._get_user_count()}\n"
                f"🛒 Активных корзин: {len(self.user_carts)}"
            )
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            await update.message.reply_text(f"⚠️ Бот испытывает проблемы\n{str(e)}")

def main():
    """Запуск бота"""
    # Проверка обязательных переменных окружения перед запуском
    required_env_vars = ['TELEGRAM_BOT_TOKEN', 'DATABASE_URL']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        error_msg = f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}"
        logger.critical(error_msg)
        raise EnvironmentError(error_msg)

    handlers = None  # Инициализируем переменную заранее
    
    try:
        # Логируем информацию о подключении к БД (для диагностики)
        db_url = os.getenv('DATABASE_URL')
        logger.info(f"Подключаемся к БД: {db_url[:20]}...")  # Логируем только начало URL для безопасности
        
        handlers = BotHandlers()  # Инициализация после проверки переменных
        
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Проверка соединения с БД
        try:
            with handlers.db.conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                logger.info("Проверка соединения с БД: успешно")
        except Exception as db_error:
            logger.critical(f"Ошибка подключения к БД: {db_error}")
            raise

        # Настройка обработчиков
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', handlers.start)],
            states={
                REGISTER_ORG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.register_org)],
                REGISTER_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.register_contact)],
            },
            fallbacks=[CommandHandler('cancel', handlers.cancel_registration)]
        )
        
        app.add_handler(conv_handler)
        app.add_handler(CommandHandler("myinfo", handlers.check_client_info))
        app.add_handler(CommandHandler("health", handlers.health_check))
        app.add_handler(InlineQueryHandler(handlers.inline_query))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_product_message))
        app.add_handler(CallbackQueryHandler(handlers.handle_quantity_buttons))
        
        logger.info("Бот запускается...")
        
        # Запуск бота
        if os.getenv("RAILWAY_ENVIRONMENT"):
            PORT = int(os.getenv("PORT", 8000))
            webhook_url = os.getenv('RAILWAY_STATIC_URL')
            
            if not webhook_url:
                logger.warning("RAILWAY_STATIC_URL не установлен, используем polling")
                app.run_polling()
            else:
                logger.info(f"Запуск в webhook режиме на порту {PORT}")
                app.run_webhook(
                    listen="0.0.0.0",
                    port=PORT,
                    url_path=TOKEN,
                    webhook_url=f"{webhook_url}/{TOKEN}"
                )
        else:
            logger.info("Запуск в polling режиме")
            app.run_polling()
            
    except psycopg2.OperationalError as db_error:
        logger.critical(f"Критическая ошибка БД: {db_error}")
    except Exception as e:
        logger.critical(f"Бот аварийно завершил работу: {str(e)}", exc_info=True)
    finally:
        try:
            if handlers is not None and hasattr(handlers, 'db'):
                handlers.db.close()
                logger.info("Соединение с БД закрыто")
        except Exception as e:
            logger.error(f"Ошибка при закрытии соединения: {e}")
        
        logger.info("Бот остановлен")

if __name__ == "__main__":
    # Дополнительная проверка для Railway
    if os.getenv("RAILWAY_ENVIRONMENT"):
        logger.info("Запуск в окружении Railway")
    
    main()
