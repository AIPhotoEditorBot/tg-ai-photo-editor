# main.py
import os
import asyncio
import aiohttp
from tempfile import NamedTemporaryFile
from io import BytesIO
from PIL import Image

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


# ----------------- Команды -----------------
@router.message(Command(commands=["start", "help"]))
async def cmd_start(message: Message):
    await message.reply(
        "👋 Привет! Я — фото-редактор.\n"
        "1) Отправь фото\n"
        "2) Затем пришли инструкцию, что с ним сделать.\n\n"
        "Например:\n• «Сделай атмосферу как на закате»\n• «Сделай в стиле аниме»\n"
    )


@router.message(F.photo)
async def on_photo(message: Message):
    pending_photos[message.from_user.id] = {"file_id": message.photo[-1].file_id}
    await message.reply("📸 Фото сохранено. Теперь пришли текст — что с ним сделать.")


@router.message()
async def on_text(message: Message):
    user_id = message.from_user.id
    if user_id not in pending_photos:
        await message.reply("Отправь фото, а затем инструкцию 😊")
        return

    prompt = message.text.strip()
    file_id = pending_photos[user_id]["file_id"]
    pending_photos.pop(user_id, None)

    await message.reply("🪄 Обрабатываю изображение, это может занять несколько секунд...")

    try:
        # Получаем URL файла
        file_obj = await bot.get_file(file_id)
        file_path = file_obj.file_path
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"

        # Скачиваем
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Ошибка скачивания файла: HTTP {resp.status}")
                image_bytes = await resp.read()
                content_type = (resp.headers.get("Content-Type") or "").lower()

        # --- Определяем расширение ---
        ext = None
        if "jpeg" in content_type or "jpg" in content_type:
            ext = ".jpg"
        elif "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"

        if not ext:
            _, path_ext = os.path.splitext(file_path or "")
            if path_ext.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                ext = path_ext.lower()

        # Если формат всё ещё неизвестен — определяем через Pillow
        if not ext:
            try:
                im = Image.open(BytesIO(image_bytes))
                fmt = (im.format or "").lower()
                if fmt in ("jpeg", "jpg"):
                    ext = ".jpg"
                elif fmt == "png":
                    ext = ".png"
                elif fmt == "webp":
                    ext = ".webp"
                else:
                    # Конвертируем в PNG
                    buf = BytesIO()
                    im.save(buf, format="PNG")
                    image_bytes = buf.getvalue()
                    ext = ".png"
            except:
                ext = ".png"

        # Сохраняем корректно
        with NamedTemporaryFile(suffix=ext, delete=False) as tmp_in:
            tmp_in.write(image_bytes)
            tmp_in_path = tmp_in.name

        # Отправляем в OpenAI
        with open(tmp_in_path, "rb") as img_file:
            result = openai.Image.create_edit(
                image=img_file,
                prompt=prompt,
                n=1,
                size="1024x1024",
                model="gpt-image-1"
            )

        image_url = result["data"][0]["url"]

        await bot.send_photo(chat_id=message.chat.id, photo=image_url, caption="✅ Готово!")

    except Exception as e:
        await message.reply(f"⚠️ Ошибка: {e}")

    finally:
        try:
            if 'tmp_in_path' in locals() and os.path.exists(tmp_in_path):
                os.remove(tmp_in_path)
        except:
            pass


# ----------------- Запуск -----------------
async def main():
    print("🤖 Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
