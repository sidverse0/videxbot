import os
import logging
import json
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot token from environment
BOT_TOKEN = os.getenv('BOT_TOKEN', '8711177949:AAFx1CsryAOHU6B6eNuht4mMHsMlUp0IkNk')
API_BASE_URL = os.getenv('API_BASE_URL', 'https://videxdownloader.onrender.com')

# Platform mapping
PLATFORM_ENDPOINTS = {
    'youtube': '/api/youtube',
    'instagram': '/api/instagram',
    'facebook': '/api/facebook'
}

# Temporary storage for user's chosen platform (in memory, can be replaced with Redis for production)
user_platform = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message with platform buttons."""
    keyboard = [
        [
            InlineKeyboardButton("▶️ YouTube", callback_data='platform:youtube'),
            InlineKeyboardButton("📸 Instagram", callback_data='platform:instagram'),
            InlineKeyboardButton("📘 Facebook", callback_data='platform:facebook')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Welcome to Video Downloader Bot!\n\n"
        "Choose a platform to download from:",
        reply_markup=reply_markup
    )

async def platform_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle platform selection callback."""
    query = update.callback_query
    await query.answer()
    platform = query.data.split(':')[1]
    user_id = query.from_user.id
    user_platform[user_id] = platform
    await query.edit_message_text(
        f"✅ Platform: *{platform.capitalize()}*\n\n"
        "Now send me the video/post/reel URL.",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle URL message from user."""
    user_id = update.message.from_user.id
    platform = user_platform.get(user_id)
    if not platform:
        await update.message.reply_text("⚠️ Please choose a platform first using /start.")
        return

    url = update.message.text.strip()
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ Invalid URL. Please send a valid link.")
        return

    # Show typing indicator
    await context.bot.send_chat_action(chat_id=update.message.chat_id, action='typing')

    # Call API
    endpoint = PLATFORM_ENDPOINTS.get(platform)
    if not endpoint:
        await update.message.reply_text("❌ Unsupported platform.")
        return

    api_url = f"{API_BASE_URL}{endpoint}?url={url}"
    try:
        response = requests.get(api_url, timeout=60)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"API request failed: {e}")
        await update.message.reply_text("❌ API request failed. Please try again later.")
        return

    if not data.get('success'):
        error_msg = data.get('error', 'Unknown error')
        await update.message.reply_text(f"❌ Error: {error_msg}")
        return

    # Prepare buttons based on type
    data_type = data.get('type')
    title = data.get('title', 'No Title')
    thumbnail = data.get('thumbnail', '')
    duration = data.get('duration', 0)

    if data_type == 'video' or data_type == 'audio':
        downloads = data.get('downloads', [])
        if not downloads:
            await update.message.reply_text("❌ No download options available.")
            return

        buttons = []
        for item in downloads:
            quality = item.get('quality', '?')
            format_ = item.get('format', '')
            type_ = item.get('type', '')
            url_link = item.get('url')
            if not url_link:
                continue
            label = f"{quality} {format_} ({type_})"
            callback_data = f"dl:{url_link}"
            buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])

        if not buttons:
            await update.message.reply_text("❌ No valid download links found.")
            return

        reply_markup = InlineKeyboardMarkup(buttons)
        msg = f"🎬 *{title}*\n"
        if duration:
            msg += f"⏱ Duration: {duration}s\n"
        msg += "\nChoose download quality:"
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

    elif data_type == 'image':
        images = data.get('images', [])
        if not images:
            await update.message.reply_text("❌ No images found.")
            return

        # For images, send first image as preview and buttons for all
        if thumbnail:
            await update.message.reply_photo(photo=thumbnail, caption=f"📷 *{title}*", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"📷 *{title}*", parse_mode='Markdown')

        buttons = []
        for i, img_url in enumerate(images, 1):
            buttons.append([InlineKeyboardButton(f"Image {i}", callback_data=f"dl:{img_url}")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text("Choose an image to get download link:", reply_markup=reply_markup)

    elif data_type == 'mixed':
        # Mixed media (carousel) – show buttons for each media type
        media = data.get('media', {})
        if not media:
            await update.message.reply_text("❌ No media found.")
            return

        await update.message.reply_text(f"📑 *{title}*\nMixed media post. Select type:", parse_mode='Markdown')
        # For simplicity, create buttons for videos and images separately
        # Videos first
        video_res = media.get('video', [])
        image_res = media.get('picture', [])
        audio_res = media.get('audio', [])
        all_buttons = []
        for item in video_res:
            label = f"🎥 {item.get('quality','?')} {item.get('format','')}"
            all_buttons.append([InlineKeyboardButton(label, callback_data=f"dl:{item.get('url')}")])
        for item in audio_res:
            label = f"🎵 {item.get('quality','?')} {item.get('format','')}"
            all_buttons.append([InlineKeyboardButton(label, callback_data=f"dl:{item.get('url')}")])
        for item in image_res:
            label = f"🖼 Image"
            all_buttons.append([InlineKeyboardButton(label, callback_data=f"dl:{item.get('url')}")])
        if all_buttons:
            await update.message.reply_text("Download options:", reply_markup=InlineKeyboardMarkup(all_buttons))
        else:
            await update.message.reply_text("❌ No download options available.")

async def download_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle download button click."""
    query = update.callback_query
    await query.answer()
    url = query.data.split(':', 1)[1]
    await query.message.reply_text(f"🔗 *Download Link:*\n`{url}`", parse_mode='Markdown', disable_web_page_preview=True)

def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set. Exiting.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(platform_selected, pattern='^platform:'))
    application.add_handler(CallbackQueryHandler(download_button, pattern='^dl:'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
