# main.py
import os
import asyncio
from io import BytesIO
from tempfile import NamedTemporaryFile

import aiohttp
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import Command

# ----------------- Загрузка .env -----------------
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Не найдены TELEGRAM_TOKEN или OPENAI_API_KEY в .env")

# ----------------- Инициализация Telegram -----------------
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ----------------- Конфиг OpenAI endpoint -----------------
OPENAI_IMAGES_EDIT_URL = "https://api.openai.com/v1/images/edits"
OPENAI_HEADERS = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

# ----------------- Словарь ожидающих фото -----------------
pending_photos: dict[int, dict] = {}

# ----------------- Вспомогательные функции -----------------
def prepare_image_bytes_for_openai(in_bytes: bytes, want_size: int = 1024) -> tuple[bytes, str]:
    """
    Открывает изображение через Pillow, конвертирует в RGB (если нужно),
    обрезает по центру в квадрат и ресайзит до want_size x want_size.
    Возвращает кортеж (bytes, mime_type) — bytes в формате PNG.
    """
    try:
        img = Image.open(BytesIO(in_bytes))
    except UnidentifiedImageError:
        raise ValueError("Формат изображения не распознан Pillow.")

    # Convert to RGBA/RGB depending on presence of alpha
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")

    # Crop to square (center) then resize
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    upper = (h - side) // 2
    right = left + side
    lower = upper + side
    img = img.crop((left, upper, right, lower))
    img = img.resize((want_size, want_size), Image.LANCZOS)

    # Save as PNG (PNG is safe; JPEG would lose alpha)
    out = BytesIO()
    img.save(out, format="PNG")
    out_bytes = out.getvalue()
    return out_bytes, "image/png"

async def openai_images_edit_send(image_bytes: bytes, prompt: str, session: aiohttp.ClientSession):
    """
    Отправляет multipart POST к /v1/images/edits с image и prompt.
    Возвращает dict JSON ответа.
    """
    form = aiohttp.FormData()
    form.add_field("model", "gpt-image-1")
    form.add_field("prompt", prompt)
    form.add_field("size", "1024x1024")
    # прикрепляем файл — даём имя и корректный content_type
    form.add_field("image", image_bytes, filename="input.png", content_type="image/png")

    # Для безопасности - явный таймаут
    timeout = aiohttp.ClientTimeout(total=180)
    async with session.post(OPENAI_IMAGES_EDIT_URL, headers=OPENAI_HEADERS, data=form, timeout=timeout) as resp:
        text = await resp.text()
        try:
            js = await resp.json()
        except Exception:
            raise RuntimeError(f"OpenAI returned non-JSON response (status {resp.status}): {text}")
        if resp.status >= 400:
            # попробуем вернуть осмысленную ошибку из OpenAI, если есть
            msg = js.get("error", {}).get("message") if isinstance(js, dict) else text
            raise RuntimeError(f"OpenAI API error (status {resp.status}): {msg}")
        return js

# ----------------- Хэндлеры -----------------
@router.message(Command(commands=["start", "help"]))
async def cmd_start(message: Message):
    await message.reply(
        "👋 Привет! Я — фото-редактор.\n"
        "1) Отправь фото (JPG/PNG/WEBP/и т.п.)\n"
        "2) Затем пришли текст — что с ним сделать.\n\n"
        "Я автоматически подготовлю изображение (сквош/масштаб) и пришлю результат."
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

    tmp_path = None
    try:
        # Получаем файл из Telegram
        file_obj = await bot.get_file(file_id)
        file_path = file_obj.file_path
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"

        # Скачиваем оригинал
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Ошибка скачивания файла: HTTP {resp.status}")
                orig_bytes = await resp.read()
                # подготовим bytes (crop/resize/convert) для OpenAI
                processed_bytes, mime = prepare_image_bytes_for_openai(orig_bytes, want_size=1024)

            # Отправляем в OpenAI
            result_json = await openai_images_edit_send(processed_bytes, prompt, session)

        # Разбор ответа: поддерживаем 'url' и 'b64_json'
        image_data = None
        if isinstance(result_json, dict) and "data" in result_json and len(result_json["data"]) > 0:
            d0 = result_json["data"][0]
            if "url" in d0 and d0["url"]:
                image_url = d0["url"]
                # просто пересылаем URL как фото
                await bot.send_photo(chat_id=message.chat.id, photo=image_url, caption="✅ Готово!")
                return
            elif "b64_json" in d0 and d0["b64_json"]:
                import base64
                raw = base64.b64decode(d0["b64_json"])
                image_data = raw

        if image_data:
            await bot.send_photo(chat_id=message.chat.id, photo=BytesIO(image_data), caption="✅ Готово!")
            return

        raise RuntimeError("Не удалось извлечь изображение из ответа OpenAI.")

    except Exception as e:
        # Если ответ OpenAI говорит о региональной блокировке, выдаём понятное сообщение
        msg = str(e)
        if "Country, region, or territory not supported" in msg or "not supported" in msg:
            msg += "\n\nПохоже, ваш аккаунт/регион не поддерживаются OpenAI Images API — это проблема учётной записи. Попробуйте использовать VPN/другую учётную запись OpenAI или Azure OpenAI (если доступно), или свяжитесь с поддержкой OpenAI."
        await message.reply(f"⚠️ Ошибка: {msg}")

# ----------------- Запуск -----------------
async def main():
    print("🤖 Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
