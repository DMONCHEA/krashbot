# config.py
import os
import logging
from typing import List, Dict, Any

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
ADMIN_IDS: List[int] = []
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
if ADMIN_CHAT_ID:
    try:
        ADMIN_IDS = [int(id.strip()) for id in ADMIN_CHAT_ID.split(",") if id.strip()]
    except ValueError as e:
        logger.error(f"Ошибка парсинга ADMIN_CHAT_ID: {e}")

# Состояния для ConversationHandler
REGISTER_ORG, REGISTER_CONTACT, ENTER_QUANTITY = range(3)

# Товары с фото (без цен)
PRODUCTS: List[Dict[str, Any]] = [
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
    "11:00 - 13:00"
]

# Для вебхуков
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Укажите ваш внешний URL, напр. https://yourdomain.com/bot
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8443))
WEBHOOK_LISTEN = os.getenv("WEBHOOK_LISTEN", "0.0.0.0")