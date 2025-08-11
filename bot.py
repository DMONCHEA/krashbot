import os
import logging
import re
from typing import Dict, Tuple, Any, Optional  # Добавляем Optional, Any, Dict, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    ApplicationBuilder
)
import psycopg2
from psycopg2 import extras

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

# Определение товаров
PRODUCTS = [
    {"id": 1, "title": "Классический круассан", "price": 100},
    {"id": 2, "title": "Миндальный круассан", "price": 150}
]
PRODUCTS_BY_TITLE = {product["title"]: product for product in PRODUCTS}

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
    
    def close(self):
        self.cursor.close()
        self.conn.close()
        logger.info("Database connection closed")

class BotHandlers:
    def __init__(self):
        self.db = Database()
        self.user_carts: Dict[int, Dict[str, Any]] = {}
        self.current_editing: Dict[int, int] = {}
    
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
        """Обработчик ввода организации"""
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
                "Пожалуйста, попробуйте снова или обратитесь в поддержку."
            )
            return REGISTER_ORG
    
    async def register_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обработчик ввода контактного лица"""
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
        """Обработчик отмены регистрации"""
        user_id = update.message.from_user.id
        logger.info(f"User {user_id} cancelled registration")
        context.user_data.clear()
        await update.message.reply_text("Регистрация отменена. Начните заново с /start.")
        return ConversationHandler.END
    
    async def check_client_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /info"""
        user_id = update.message.from_user.id
        organization, contact_person = self.db.get_client(user_id)
        if organization and contact_person:
            await update.message.reply_text(
                f"Ваши данные:\nОрганизация: {organization}\nКонтактное лицо: {contact_person}"
            )
        else:
            await update.message.reply_text("Вы не зарегистрированы. Пожалуйста, используйте /start для регистрации.")
    
    async def handle_product_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик сообщений с товарами"""
        user_id = update.message.from_user.id
        logger.info(f"handle_product_message called for user {user_id} with text '{update.message.text}' in chat {update.message.chat.type}")
        
        # Проверка регистрации
        organization, contact_person = self.db.get_client(user_id)
        if not organization:
            logger.info(f"User {user_id} is not registered, ignoring product message")
            await update.message.reply_text("Пожалуйста, завершите регистрацию с помощью команды /start")
            return
        
        message_text = update.message.text.strip()
        first_line = message_text.split('\n', 1)[0].strip()
        
        if (product := PRODUCTS_BY_TITLE.get(first_line)):
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
        else:
            await update.message.reply_text("Такой продукт не найден. Попробуйте снова.")
    
    async def show_cart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать корзину пользователя"""
        user_id = update.message.from_user.id
        if user_id not in self.user_carts or not self.user_carts[user_id]["items"]:
            await update.message.reply_text("Ваша корзина пуста.")
            return
        
        cart = self.user_carts[user_id]["items"]
        cart_text = "Ваша корзина:\n"
        total = 0
        for idx, item in enumerate(cart):
            product = item["product"]
            quantity = item["quantity"]
            item_total = product["price"] * quantity
            total += item_total
            cart_text += f"{idx + 1}. {product['title']} - {quantity} шт. - {item_total} руб.\n"
        
        cart_text += f"\nИтого: {total} руб."
        await update.message.reply_text(cart_text)
    
    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stats для админов"""
        user_id = update.message.from_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("Эта команда доступна только администраторам.")
            return
        
        clients = self.db.get_all_clients()
        client_count = len(clients)
        await update.message.reply_text(f"Количество зарегистрированных клиентов: {client_count}")
    
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

def main():
    """Запуск бота"""
    try:
        application = ApplicationBuilder().token(TOKEN).build()
        handlers = BotHandlers()
        
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
        
        # Регистрация MessageHandler для товаров (только для зарегистрированных пользователей)
        registered_users = [user_id for user_id, (org, _) in handlers.db.get_all_clients().items() if org]
        application.add_handler(MessageHandler(
            filters=filters.TEXT & ~filters.COMMAND & filters.User(user_ids=registered_users),
            callback=handlers.handle_product_message,
            block=False
        ))
        
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
