# main.py
import os
import asyncio
import aiohttp
from tempfile import NamedTemporaryFile

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv

import openai

# ----------------- Подгружаем .env из той же папки -----------------
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Не найдены TELEGRAM_TOKEN или OPENAI_API_KEY в .env")

# ----------------- Инициализация -----------------
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# openai (старый интерфейс 0.28.0)
openai.api_key = OPENAI_API_KEY

# словарь ожидающих фото: user_id -> file_id
pending_photos: dict[int, dict] = {}

# ----------------- Хэндлеры -----------------
@router.message(Command(commands=["start", "help"]))
async def cmd_start(message: Message):
    await message.reply(
        "👋 Привет! Я — фото-редактор. Отправь мне фото, а затем — инструкцию, "
        "как его изменить.\n\n"
        "Пример: 'Сделай в стиле аниме' или 'Добавь закат на задний фон'."
    )

@router.message(F.photo)
async def on_photo(message: Message):
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id
    pending_photos[user_id] = {"file_id": file_id}
    await message.reply("📸 Фото сохранено. Теперь пришли текстовую инструкцию — что сделать с ним.")

@router.message()
async def on_text(message: Message):
    user_id = message.from_user.id
    # Если от пользователя нет ожидающего фото — подсказка
    if user_id not in pending_photos:
        await message.reply("Отправь фото, а затем инструкцию, что с ним сделать 😊")
        return

    prompt = message.text.strip()
    file_id = pending_photos[user_id]["file_id"]
    # удаляем ожидание
    pending_photos.pop(user_id, None)

    await message.reply("🪄 Обрабатываю изображение, это может занять несколько секунд...")

    try:
        # Получаем путь к файлу в Telegram
        file_obj = await bot.get_file(file_id)
        file_path = file_obj.file_path
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"

        # Скачиваем файл (aiohttp)
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Ошибка скачивания файла: HTTP {resp.status}")
                image_bytes = await resp.read()

        # Сохраняем временный файл
        with NamedTemporaryFile(suffix=".png", delete=False) as tmp_in:
            tmp_in.write(image_bytes)
            tmp_in_path = tmp_in.name

        # Отправляем в OpenAI (openai==0.28.0 интерфейс)
        # Используем create_edit (рабочий в 0.28.0)
        with open(tmp_in_path, "rb") as img_file:
            result = openai.Image.create_edit(
                image=img_file,
                prompt=prompt,
                n=1,
                size="1024x1024",
                model="gpt-image-1"
            )

        # result должен содержать URL
        image_url = None
        if result and "data" in result and len(result["data"]) > 0:
            image_url = result["data"][0].get("url")

        if not image_url:
            raise RuntimeError("Не удалось получить результат от OpenAI (нет URL в ответе).")

        # Отправляем результат пользователю
        await bot.send_photo(chat_id=message.chat.id, photo=image_url, caption="✅ Готово!")

    except Exception as e:
        await message.reply(f"⚠️ Ошибка: {e}")

    finally:
        # очищаем временный файл (если он остался)
        try:
            if 'tmp_in_path' in locals() and os.path.exists(tmp_in_path):
                os.remove(tmp_in_path)
        except Exception:
            pass

# ----------------- Запуск -----------------
async def main() -> None:
    print("🤖 Bot is running (aiogram v3)...")
    # dp.start_polling принимает bot
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
