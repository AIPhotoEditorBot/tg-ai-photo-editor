# main.py
import os
import asyncio
import aiohttp
import imghdr
from tempfile import NamedTemporaryFile
from io import BytesIO

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv

import openai

# ----------------- Загружаем .env -----------------
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Не найдены TELEGRAM_TOKEN или OPENAI_API_KEY в .env")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai.api_key = OPENAI_API_KEY

pending_photos: dict[int, dict] = {}

# ---- Вспомогательная логика для определения формата ----
def detect_ext_from_bytes(b: bytes, file_path_hint: str | None = None, content_type: str | None = None) -> str | None:
    """Вернёт расширение файла: '.jpg' / '.png' / '.webp' или None если не удалось."""
    if content_type:
        ct = content_type.lower()
        if "jpeg" in ct or "jpg" in ct:
            return ".jpg"
        if "png" in ct:
            return ".png"
        if "webp" in ct:
            return ".webp"

    # по hint расширения в пути
    if file_path_hint:
        _, ext = os.path.splitext(file_path_hint)
        ext = ext.lower()
        if ext in (".jpg", ".jpeg"):
            return ".jpg"
        if ext == ".png":
            return ".png"
        if ext == ".webp":
            return ".webp"

    # используем imghdr для jpeg/png
    kind = imghdr.what(None, h=b)
    if kind == "jpeg":
        return ".jpg"
    if kind == "png":
        return ".png"
    if kind == "webp":
        return ".webp"

    # простая проверка сигнатуры WEBP (RIFF....WEBP)
    if len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP":
        return ".webp"

    # проверим сигнатуру JPEG/PNG вручную на всякий случай
    if len(b) >= 2 and b[0:2] == b"\xff\xd8":
        return ".jpg"
    if len(b) >= 8 and b[0:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"

    return None

# ----------------- Хэндлеры -----------------
@router.message(Command(commands=["start", "help"]))
async def cmd_start(message: Message):
    await message.reply(
        "👋 Привет! Я — фото-редактор.\n"
        "1) Отправь фото\n"
        "2) Затем пришли инструкцию, что сделать.\n\n"
        "Поддерживаемые форматы: JPG/JPEG, PNG, WEBP."
    )

@router.message(F.photo)
async def on_photo(message: Message):
    pending_photos[message.from_user.id] = {"file_id": message.photo[-1].file_id}
    await message.reply("📸 Фото сохранено. Теперь пришли текст — что с ним сделать.")

@router.message()
async def on_text(message: Message):
    user_id = message.from_user.id
    if user_id not in pending_photos:
        await message.reply("Сначала отправь фото, затем инструкцию 😊")
        return

    prompt = message.text.strip()
    file_id = pending_photos[user_id]["file_id"]
    pending_photos.pop(user_id, None)

    await message.reply("🪄 Обрабатываю изображение, это может занять несколько секунд...")

    tmp_in_path = None
    try:
        # Получаем файл из Telegram
        file_obj = await bot.get_file(file_id)
        file_path = file_obj.file_path  # hint с расширением иногда есть
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"

        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Ошибка скачивания файла: HTTP {resp.status}")
                image_bytes = await resp.read()
                content_type = (resp.headers.get("Content-Type") or "").lower()

        # Определяем расширение (jpg/png/webp)
        ext = detect_ext_from_bytes(image_bytes, file_path_hint=file_path, content_type=content_type)

        if not ext:
            # Если не определили формат — сообщаем пользователю
            await message.reply(
                "Не удалось определить формат изображения. Пожалуйста, пришли фото в формате JPG/JPEG, PNG или WEBP."
            )
            return

        # Сохраняем временный файл с правильным расширением
        with NamedTemporaryFile(suffix=ext, delete=False) as tmp_in:
            tmp_in.write(image_bytes)
            tmp_in_path = tmp_in.name

        # Отправляем изображение в OpenAI (старый интерфейс 0.28.0)
        with open(tmp_in_path, "rb") as img_file:
            result = openai.Image.create_edit(
                image=img_file,
                prompt=prompt,
                n=1,
                size="1024x1024",
                model="gpt-image-1"
            )

        # Парсим результат
        image_url = None
        if result and "data" in result and len(result["data"]) > 0:
            # В старом API возвращается data[0].url
            image_url = result["data"][0].get("url")

        if not image_url:
            raise RuntimeError("Не удалось получить URL результата от OpenAI.")

        await bot.send_photo(chat_id=message.chat.id, photo=image_url, caption="✅ Готово!")

    except Exception as e:
        # Показываем пользователю информативную ошибку
        await message.reply(f"⚠️ Ошибка: {e}")

    finally:
        try:
            if tmp_in_path and os.path.exists(tmp_in_path):
                os.remove(tmp_in_path)
        except Exception:
            pass

# ----------------- Запуск -----------------
async def main():
    print("🤖 Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())