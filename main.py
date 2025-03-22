import telebot
from telebot.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from config import BOT_TOKEN, PRIVATE_CHANNEL_ID, ADMIN_TELEGRAM_ID  # Add your Telegram ID to the config

bot = telebot.TeleBot(BOT_TOKEN)

# List to store user IDs who subscribed
subscribed_users = set()

# Initialize SQLite database
conn = sqlite3.connect('messages.db', check_same_thread=False)
cursor = conn.cursor()

# Create table to store messages and users
cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    tags TEXT
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT,
    is_premium BOOLEAN
)
''')
conn.commit()

# Function to set available commands
def set_bot_commands():
    commands = [
        BotCommand("start", "Start the bot"),
        # BotCommand("help", "Show available commands"),
        BotCommand("find", "Finde a module"),
    ]
    bot.set_my_commands(commands)
# Call this function when the bot starts
# set_bot_commands()

# Handle new messages in the channel
@bot.channel_post_handler(content_types=['text', 'photo', 'document'])
def forward_channel_messages(message):
    # Extract tags from the message text or caption (words start with #)
    tags = []
    if message.content_type == 'text':
        tags = [word for word in message.text.split() if word.startswith('#')]
    elif message.content_type in ['photo', 'document']:
        if message.caption:
            tags = [word for word in message.caption.split() if word.startswith('#')]

    # Save message ID and tags to the database
    for tag in tags:
        cursor.execute('INSERT INTO messages (message_id, tags) VALUES (?, ?)', (message.message_id, tag))
    conn.commit()

# /start command - Send welcome message with buttons
@bot.message_handler(commands=["start"])
def start_command(message):
    user = message.from_user
    user_data = (user.id, user.username, user.first_name, user.last_name, user.language_code, user.is_premium)

    # log user information
    cursor.execute('''
    INSERT OR REPLACE INTO users (id, username, first_name, last_name, language_code, is_premium)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', user_data)
    conn.commit()

    start_message = (
        "👋 Welcome to the RUB Exames Bot!\n\n"
        "Here are some commands to get you started:\n"
        "/find - Choose an option to find a module\n\n"
        "You can use the /find command to search for modules by numbers or names."
    )

    bot.send_message(
        message.chat.id,
        start_message,
    )

# /find command - Choose an option to find a module
@bot.message_handler(commands=["find"])
def choose_option(message):
    keyboard = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton("Number", callback_data="choose_numbers"),
        InlineKeyboardButton("Name", callback_data="choose_names")
    ]
    keyboard.add(*buttons)
    bot.send_message(message.chat.id, "Find a module using:", reply_markup=keyboard)

# Handle user's initial selection
@bot.callback_query_handler(func=lambda call: call.data in ["choose_numbers", "choose_names"])
def handle_initial_choice(call):
    chosen_option = call.data

    # Fetch tags from the database
    cursor.execute('SELECT DISTINCT tags FROM messages')
    rows = cursor.fetchall()
    all_tags = [row[0] for row in rows if row[0]]

    if chosen_option == "choose_numbers":
        OPTIONS = sorted([tag for tag in all_tags if tag[1:].isdigit()])
        keyboard = InlineKeyboardMarkup(row_width=3)

    else:
        OPTIONS = sorted([tag for tag in all_tags if not tag[1:].isdigit()])
        keyboard = InlineKeyboardMarkup(row_width=2)

    if not OPTIONS:
        bot.send_message(call.message.chat.id, "No tags available.")
        keyboard = InlineKeyboardMarkup(row_width=2)
        return

    buttons = [InlineKeyboardButton(option, callback_data=option) for option in OPTIONS]
    buttons.append(InlineKeyboardButton("Go Back", callback_data="go_back"))
    keyboard.add(*buttons)

    bot.edit_message_text("Choose a Module:", call.message.chat.id, call.message.message_id, reply_markup=keyboard)

# Handle user's tag selection or go back action
@bot.callback_query_handler(func=lambda call: call.data in [row[0] for row in cursor.execute('SELECT DISTINCT tags FROM messages').fetchall()] + ["go_back"])
def handle_choice(call):
    if call.data == "go_back":
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = [
            InlineKeyboardButton("Number", callback_data="choose_numbers"),
            InlineKeyboardButton("Name", callback_data="choose_names")
        ]
        keyboard.add(*buttons)

        bot.edit_message_text("Find a module using:", call.message.chat.id, call.message.message_id, reply_markup=keyboard)

    else:
        chosen_option = call.data  # Get the selected option

        # Fetch message IDs associated with the chosen tag
        cursor.execute('SELECT message_id FROM messages WHERE tags = ?', (chosen_option,))
        message_ids = cursor.fetchall()

        if not message_ids:
            bot.send_message(call.message.chat.id, "No messages found for the selected tag.")
            return

        # Forward each message to the user
        for message_id in message_ids:
            try:
                bot.forward_message(call.message.chat.id, PRIVATE_CHANNEL_ID, message_id[0])
            except Exception as e:
                print(f"Error forwarding message ID {message_id[0]}: {e}")


# Start the bot with error handling
print("Bot is running...")
while True:
    try:
        bot.polling()
    except Exception as e:
        error_message = f"An error occurred: {e}"
        print(error_message)
        bot.send_message(ADMIN_TELEGRAM_ID, error_message)