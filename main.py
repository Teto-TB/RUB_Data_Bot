import telebot, time
from telebot.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from config import BOT_TOKEN, PRIVATE_CHANNEL_ID, ADMIN_TELEGRAM_ID  

bot = telebot.TeleBot(BOT_TOKEN)


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
        BotCommand("find", "Finde a module"),
        BotCommand("send", "Share your PDF-Exames with others"),
        BotCommand("help", "See the available commands"),
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
        if message.text == "/delete":
            if message.reply_to_message:
                try:    
                    # Delete the message from the database
                    cursor.execute(f"DELETE FROM messages WHERE message_id = {int(message.reply_to_message.message_id)}")
                    conn.commit()
                except Exception as e:
                    print(f"❌ Failed to delete from DB: {e}")

                try:
                    # Delete the message you replied to
                    bot.delete_message(PRIVATE_CHANNEL_ID, message.reply_to_message.message_id)
                    print(f"Deleted message: {message.reply_to_message.message_id}")
                except Exception as e:
                    print(f"❌ Failed to delete replied message: {e}")

                try:
                    # Delete the /delete command message itself
                    bot.delete_message(PRIVATE_CHANNEL_ID, message.message_id)
                except Exception as e:
                    print(f"❌ Failed to delete command message: {e}")
                
            else:
                bot.reply_to(message, "❗ Reply to a message with /delete to delete it.")
                return
            
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
        f"👋 *Welcome {user.first_name or 'there'} to the RUB Exams Bot!*\n\n"
        "📚 This bot helps you find and share past exams easily.\n\n"
        "Here’s what you can do:\n"
        "🔍 /find — Search for a module\n"
        "📤 /send — Share your PDF exams with others\n"
        "Let's make learning easier together! 🚀"
    )
    bot.send_message(
        message.chat.id,
        start_message,
    )

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "📌 *Available Commands:*\n\n"
        "/start - Start the bot and get a welcome message\n"
        "/find - Search for a module\n"
        "/send - Share your PDF exams with the community\n"
        "/help - Show this help message\n"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')


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
                bot.send_message(ADMIN_TELEGRAM_ID, f"Error forwarding message ID {message_id[0]}: {e}")

# Dictionary to track users waiting to send a PDF
waiting_for_pdf = {}
@bot.message_handler(commands=['send'])
def ask_for_pdf(message):
    bot.reply_to(message, "Please send the PDF file and write the name and the number of the module in the caption like this:\n\n #Mathe #202212")
    waiting_for_pdf[message.from_user.id] = True

@bot.message_handler(content_types=['document'])
def handle_document(message):
    user_id = message.from_user.id

    # Check if the user was asked to send a PDF
    if waiting_for_pdf.get(user_id):
        if message.document.mime_type == 'application/pdf':
            # Forward to admin
            bot.forward_message(ADMIN_TELEGRAM_ID, message.chat.id, message.message_id)
            bot.reply_to(message, "PDF has been forwarded to the admin.✅ \n\n Your file will be validated and published soon.")
        else:
            bot.reply_to(message, "❌ Please send a valid PDF file.")

        waiting_for_pdf[user_id] = False
    else:
        bot.reply_to(message, "Type /send to start the sending process.")

# Start the bot with error handling
print("Bot is running...")
if __name__=='__main__':
    while True:
        try:
            bot.polling(non_stop=True, interval=0)
        except Exception as e:
            error_message = f"An error occurred: {e}"
            print(error_message)
            bot.send_message(ADMIN_TELEGRAM_ID, error_message)
            time.sleep(5)
            continue        
