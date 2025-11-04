import os
import aiohttp
from tempfile import NamedTemporaryFile
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import openai
from dotenv import load_dotenv

# ----------------- Подгружаем .env -----------------
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

# ----------------- Ключи -----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Не найдены TELEGRAM_TOKEN или OPENAI_API_KEY в .env")

# ----------------- Настройка бота и OpenAI -----------------
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

# Только глобальный API ключ для старой версии OpenAI
openai.api_key = OPENAI_API_KEY

# ----------------- Словарь ожидающих фото -----------------
pending_photos = {}  # user_id -> {"file_id": str}

# ----------------- Хэндлеры -----------------
@dp.message_handler(commands=["start", "help"])
async def start_cmd(message: types.Message):
    await message.reply(
        "👋 Привет! Отправь мне фото и подпиши, как нужно его изменить.\n\n"
        "Например: 'Сделай в стиле аниме' или 'добавь закат на фоне'."
    )

@dp.message_handler(content_types=["photo"])
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id
    pending_photos[user_id] = {"file_id": file_id}
    await message.reply("📸 Фото получено. Теперь пришли текстовую инструкцию — что сделать с ним.")

@dp.message_handler(lambda m: m.text and m.from_user.id in pending_photos)
async def handle_prompt(message: types.Message):
    user_id = message.from_user.id
    prompt = message.text.strip()
    file_id = pending_photos[user_id]["file_id"]
    pending_photos.pop(user_id, None)

    await message.reply("🪄 Обрабатываю изображение, подожди немного...")

    try:
        # Скачиваем фото с Telegram
        file = await bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}"

        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                image_bytes = await resp.read()

        # Сохраняем временный файл
        with NamedTemporaryFile(suffix=".png", delete=False) as tmp_in:
            tmp_in.write(image_bytes)
            tmp_in_path = tmp_in.name

        # ----------------- Старый метод OpenAI 0.28 -----------------
        with open(tmp_in_path, "rb") as img_file:
            result = openai.Image.create_edit(
                model="gpt-image-1",
                image=img_file,
                prompt=prompt,
                size="1024x1024"
            )

        image_url = result['data'][0]['url']
        await message.reply_photo(photo=image_url, caption="✅ Готово!")

        # Удаляем временный файл
        os.remove(tmp_in_path)

    except Exception as e:
        await message.reply(f"⚠️ Ошибка: {e}")

@dp.message_handler()
async def fallback(message: types.Message):
    await message.reply("Отправь фото и инструкцию, чтобы я понял, что нужно сделать 😊")

# ----------------- Запуск бота -----------------
if __name__ == "__main__":
    print("🤖 Bot is running...")
    executor.start_polling(dp, skip_updates=True)
