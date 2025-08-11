# bot.py
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    InlineQueryHandler,
    CallbackQueryHandler
)
from config import TOKEN, WEBHOOK_URL, WEBHOOK_PORT, WEBHOOK_LISTEN, logger, REGISTER_ORG, REGISTER_CONTACT, ENTER_QUANTITY
from db import Database
from handlers import BotHandlers

async def error_handler(update, context):
    logger.error(f"Update {update} caused error {context.error}")
    if update.message:
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже или свяжитесь с поддержкой.")

def main():
    try:
        db = Database()
        handlers = BotHandlers(db)
        
        application = ApplicationBuilder().token(TOKEN).build()
        
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", handlers.start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_product_message)
            ],
            states={
                REGISTER_ORG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.register_org)],
                REGISTER_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.register_contact)],
                ENTER_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.enter_quantity)],
            },
            fallbacks=[CommandHandler("cancel", handlers.cancel_registration)],
            persistent=False,
            name="registration_conversation"
        )
        application.add_handler(conv_handler)
        
        application.add_handler(InlineQueryHandler(handlers.inline_query))
        application.add_handler(CallbackQueryHandler(handlers.handle_callback_query))
        application.add_handler(CommandHandler("info", handlers.check_client_info))
        application.add_handler(CommandHandler("stats", handlers.admin_stats))
        application.add_handler(CommandHandler("add_admin", handlers.add_admin))
        application.add_handler(CommandHandler("remove_admin", handlers.remove_admin))
        
        application.add_error_handler(error_handler)
        
        logger.info("Бот запущен на вебхуках")
        application.run_webhook(
            listen=WEBHOOK_LISTEN,
            port=WEBHOOK_PORT,
            url_path=TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        if 'db' in locals():
            db.close()

if __name__ == '__main__':
    main()
