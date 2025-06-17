import logging
import time
import sqlite3
from telebot import TeleBot
from telebot.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, PRIVATE_CHANNEL_ID, ADMIN_TELEGRAM_ID

# ─── 1. CONFIGURE LOGGING 

# Configure logging to file and console
# file_handler = RotatingFileHandler(
#     'bot.log',
#     maxBytes=5 * 1024 * 1024,  # 5 MB
# )
# file_handler.setLevel(logging.DEBUG)
# file_formatter = logging.Formatter(
#     '%(asctime)s %(levelname)-8s %(name)s %(message)s'
# )
# file_handler.setFormatter(file_formatter)

# console_handler = logging.StreamHandler()
# console_handler.setLevel(logging.INFO)
# console_formatter = logging.Formatter(
#     '%(asctime)s %(levelname)-8s %(message)s'
# )
# console_handler.setFormatter(console_formatter)

# logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console_handler])

# Configure logging only to console
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(name)s %(message)s'
)
logger = logging.getLogger(__name__)
logger.debug("Logger configured, starting up")

# ─── 2. INITIALIZE BOT 
bot = TeleBot(BOT_TOKEN)
logger.debug("TeleBot initialized")

# ─── 3. SQLite DATABASE SETUP 
def init_db():
    logger.debug("Initializing database (WAL mode + tables)")

    # Create tables to store messages and users
    with sqlite3.connect('messages.db', check_same_thread=False) as conn:
        # Enable WAL mode for better concurrency
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER UNIQUE,
                tags TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                is_premium BOOLEAN
            )
        ''')
    logger.debug("Database initialized")

def get_db_connection():
    logger.debug("Opening new DB connection")
    conn = sqlite3.connect('messages.db', check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL;')
    cursor = conn.cursor()
    logger.debug("DB connection opened: %s", conn)
    return conn, cursor

# ─── 4. SET BOT COMMANDS 
def set_bot_commands():
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("find", "Find a module"),
        BotCommand("send", "Share your PDF exams"),
        BotCommand("help", "See available commands"),
    ]
    logger.debug("Setting bot commands: %s", commands)
    bot.set_my_commands(commands)
    logger.info("Bot commands set")

# ─── 5. HANDLERS 

# Handle new messages in the channel
@bot.channel_post_handler(content_types=['text', 'photo', 'document'])
def forward_channel_messages(message):
    logger.debug(
        "Entered forward_channel_messages: id=%s, type=%s",
        message.message_id, message.content_type
    )
    conn, cursor = get_db_connection()
    try:
        # Handle /delete
        if message.content_type == 'text' and message.text == '/delete' and message.reply_to_message:
            logger.info("Processing /delete for message %s", message.reply_to_message.message_id)
            try:
                # Delete the message from the database
                with sqlite3.connect('messages.db', check_same_thread=False) as del_conn:
                    del_conn.execute('PRAGMA journal_mode=WAL;')
                    del_conn.execute(
                        'DELETE FROM messages WHERE message_id = ?',
                        (message.reply_to_message.message_id,)
                    )
                
                # Delete the message you replied to
                bot.delete_message(PRIVATE_CHANNEL_ID, message.reply_to_message.message_id)
                # Delete the /delete command message itself
                bot.delete_message(PRIVATE_CHANNEL_ID, message.message_id)
                logger.info("Deleted message %s and command %s",
                            message.reply_to_message.message_id, message.message_id)
            except Exception as e:
                logger.exception("Failed to delete messages from DB or channel")
            return

        # Extract tags from the message text or caption (words start with # )
        if message.content_type == 'text':
            tags = [w for w in message.text.split() if w.startswith('#')]
        elif message.content_type in ('photo', 'document') and message.caption:
            tags = [w for w in message.caption.split() if w.startswith('#')]
        else:
            tags = []
        logger.debug("Extracted tags: %r", tags)

        # Store tags and message IDs in the database
        for tag in tags:
            try:
                cursor.execute(
                    'INSERT OR IGNORE INTO messages (message_id, tags) VALUES (?, ?)',
                    (message.message_id, tag)
                )
                logger.info("Inserted tag '%s' for message_id %s", tag, message.message_id)
            except Exception:
                logger.exception("Failed to insert tag '%s' for message_id %s", tag, message.message_id)
        conn.commit()
        logger.debug("Committed DB transaction in forward_channel_messages")
    except Exception:
        logger.exception("Unhandled exception in forward_channel_messages")
    finally:
        conn.close()
        logger.debug("Closed DB connection in forward_channel_messages")

# /start command - Send welcome message with buttons
@bot.message_handler(commands=['start'])
def start_command(message):
    logger.info("Received /start from user %s (%s)", message.from_user.id, message.from_user.username)
    user = message.from_user
    with sqlite3.connect('messages.db', check_same_thread=False) as conn:
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('''
            INSERT OR REPLACE INTO users
            (id, username, first_name, last_name, language_code, is_premium)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            user.language_code,
            user.is_premium
        ))
        logger.debug("Upserted user into DB: %s", user.id)

    welcome = (
        f"👋 *Welcome {user.first_name or 'there'} to the RUB Exams Bot!*\n\n"
        "📚 This bot helps you find and share past exams easily.\n\n"
        "/find — Search for a module\n"
        "/send — Share your PDF exams\n"
        "/help — See available commands"
    )
    bot.send_message(message.chat.id, welcome, parse_mode='Markdown')
    logger.info("Sent welcome message to %s", message.from_user.id)


@bot.message_handler(commands=['help'])
def help_command(message):
    logger.info("Received /help from user %s", message.from_user.id)
    help_text = (
        "📌 *Available Commands:*\n\n"
        "/start — Start the bot and get a welcome message\n"
        "/find — Search for a module\n"
        "/send — Share your PDF exams with the community\n"
        "/help — Show this help message"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')
    logger.debug("Sent help message to %s", message.from_user.id)

# /find command - Choose an option to find a module
@bot.message_handler(commands=['find'])
def choose_option(message):
    logger.info("Received /find from user %s", message.from_user.id)
    keyboard = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton("Number", callback_data="choose_numbers"),
        InlineKeyboardButton("Name", callback_data="choose_names")
    ]
    keyboard.add(*buttons)
    bot.send_message(message.chat.id, "Find a module by:", reply_markup=keyboard)
    logger.debug("Sent find-options keyboard to %s", message.from_user.id)


# Handle user's initial selection
@bot.callback_query_handler(func=lambda call: call.data in ["choose_numbers", "choose_names"])
def handle_initial_choice(call):
    logger.info("User %s chose initial option %s", call.from_user.id, call.data)
    option = call.data

    # Fetch tags from the database
    with sqlite3.connect('messages.db', check_same_thread=False) as conn:
        conn.execute('PRAGMA journal_mode=WAL;')
        rows = conn.execute('SELECT DISTINCT tags FROM messages').fetchall()
    all_tags = [r[0] for r in rows if r[0]]
    logger.debug("Fetched %s distinct tags", len(all_tags))

    if option == "choose_numbers":
        choices = sorted([t for t in all_tags if t[1:].isdigit()])
        keyboard = InlineKeyboardMarkup(row_width=3)
    else:
        choices = sorted([t for t in all_tags if not t[1:].isdigit()])
        keyboard = InlineKeyboardMarkup(row_width=2)
    logger.debug("Filtered choices (%s): %r", option, choices)

    if not choices:
        bot.send_message(call.message.chat.id, "No tags available.")
        logger.warning("No tags available for option %s", option)
        return

    buttons = [InlineKeyboardButton(c, callback_data=c) for c in choices]
    buttons.append(InlineKeyboardButton("Go Back", callback_data="go_back"))
    keyboard.add(*buttons)
    bot.edit_message_text(
        "Choose a module:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )
    logger.debug("Edited message with module choices for %s", call.from_user.id)


# Handle user's tag selection or go back action
@bot.callback_query_handler(func=lambda call: call.data not in ["choose_numbers", "choose_names"])
def handle_choice(call):
    logger.info("Handling choice '%s' for user %s", call.data, call.from_user.id)
    data = call.data

    if data == "go_back":
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = [
            InlineKeyboardButton("Number", callback_data="choose_numbers"),
            InlineKeyboardButton("Name", callback_data="choose_names")
        ]
        keyboard.add(*buttons)
        bot.edit_message_text(
            "Find a module by:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )
        logger.debug("User %s went back to initial menu", call.from_user.id)
        return

    conn, cursor = get_db_connection()
    try:
        # Fetch message IDs associated with the chosen tag
        cursor.execute('SELECT message_id FROM messages WHERE tags = ?', (data,))
        rows = cursor.fetchall()
        logger.debug("Found %s messages for tag '%s'", len(rows), data)

        if not rows:
            bot.send_message(call.message.chat.id, "No messages found for the selected tag.")
            logger.warning("No messages for tag '%s'", data)
            return

        # Forward each message to the user
        for (mid,) in rows:
            try:
                bot.forward_message(call.message.chat.id, PRIVATE_CHANNEL_ID, mid)
                logger.info("Forwarded message %s to user %s", mid, call.from_user.id)
            except Exception as e:
                logger.exception("Error forwarding message ID %s", mid)
                bot.send_message(ADMIN_TELEGRAM_ID, f"Error forwarding message ID {mid}: {e}")
    except Exception:
        logger.exception("Unhandled exception in handle_choice")
    finally:
        conn.close()
        logger.debug("Closed DB connection in handle_choice")


# ─── 6. SEND COMMAND HANDLERS 
# Dictionary to track users waiting to send a PDF
waiting_for_pdf = {}

@bot.message_handler(commands=['send'])
def ask_for_pdf(message):
    logger.info("Received /send from user %s", message.from_user.id)
    bot.reply_to(
        message,
        "Please send the PDF file and include tags in the caption like:\n\n#Mathe #202212"
    )
    waiting_for_pdf[message.from_user.id] = True
    logger.debug("Set waiting_for_pdf[%s] = True", message.from_user.id)

@bot.message_handler(content_types=['document'])
def handle_document(message):
    logger.info("Received document from user %s", message.from_user.id)
    user_id = message.from_user.id

     # Check if the user was asked to send a PDF
    if not waiting_for_pdf.get(user_id):
        logger.debug("Unexpected document (no /send), replying guidance")
        return bot.reply_to(message, "Type /send to start the upload process.")

    waiting_for_pdf[user_id] = False
    logger.debug("Reset waiting_for_pdf[%s] to False", user_id)

    if message.document.mime_type != 'application/pdf':
        logger.warning("User %s sent invalid mime_type %s", user_id, message.document.mime_type)
        return bot.reply_to(message, "❌ Please send a valid PDF file.")

    # Forward to admin
    bot.forward_message(ADMIN_TELEGRAM_ID, message.chat.id, message.message_id)
    bot.reply_to(message, "✅ PDF forwarded to admin. It will be published soon.")
    logger.info("Forwarded PDF message %s from user %s to admin", message.message_id, user_id)


# ─── 7. RUN BOT 
if __name__ == '__main__':
    logger.info("Starting bot setup")
    init_db()
    set_bot_commands()
    logger.info("Bot setup complete, entering polling loop")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=5)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception:
        logger.exception("Unexpected error, restarting in 5 seconds")
        bot.send_message(ADMIN_TELEGRAM_ID, f"Unexpected error: {Exception}")

        time.sleep(5)
        bot.infinity_polling(timeout=60, long_polling_timeout=5)

# ─── 8. OPTIONAL: RUNNING IN WHILE 
# if __name__ == '__main__':
#     logger.info("Starting bot setup")
#     init_db()
#     set_bot_commands()
#     logger.info("Bot setup complete, entering polling loop")

#     while True:
#         try:
#             bot.infinity_polling(timeout=60, long_polling_timeout=5)
#         except KeyboardInterrupt:
#             logger.info("Bot stopped by user (KeyboardInterrupt)")
#             break   # exit the loop & script cleanly
#         except Exception as e:
#             # Catch *any* other error, notify and restart
#             logger.exception("Unexpected error, restarting in 5 seconds")
#             try:
#                 bot.send_message(ADMIN_TELEGRAM_ID, f"Unexpected error: {e}")
#             except Exception:
#                 logger.warning("Failed to send error alert to admin")
#             time.sleep(5)
#             # loop will repeat, calling polling again
