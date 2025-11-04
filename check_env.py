import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
print("Путь к .env:", dotenv_path)

if not os.path.exists(dotenv_path):
    print("⚠️ Файл .env не найден по этому пути!")
else:
    print("✅ Файл .env найден.")

load_dotenv(dotenv_path)

print("TELEGRAM_TOKEN =", os.getenv("TELEGRAM_TOKEN"))
print("OPENAI_API_KEY =", os.getenv("OPENAI_API_KEY"))
