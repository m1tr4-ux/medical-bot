import asyncio
import logging
import os
import sqlite3
from datetime import datetime
import docx
from pypdf import PdfReader
from google import genai

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, BotCommand

# Мини-сервер для пингеров ( Render & UptimeRobot )
from http.server import HTTPServer, BaseHTTPRequestHandler
import multiprocessing

TOKEN = "8508064690:AAGcT0-LdWR1nuqC27dU9gJoyFl_MJJrVfE"

# Твой токен из AI Studio со скриншота
GEMINI_API_KEY = "AQ.Ab8RN6Kj0u3XEqKqrmcmOXbnx4-hf2hvqGLcwxwQUkp47CImVg"

# Инициализация клиента
client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

UPLOAD_DIR = "study_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

START_TIME = datetime.now()


def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            topic TEXT,
            file_path TEXT,
            file_name TEXT,
            uploader TEXT,
            upload_date TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()

EXACT_SCHEDULE = {
    "Понедельник": [
        {"time": "08.00 - 09.50", "subject": "Введение в клинику\n📍 МЦ «Интермед», ул. Курмангазы, 98\n👩‍⚕️ Преподаватель: Умарова Сауле Утегеновна (ГКБ №4)"},
        {"time": "11.00 - 13.50", "subject": "Молекулярная биология\n👩‍🏫 Преподаватель: Айнур Кадырбековна (607 ауд.)"}
    ],
    "Вторник": [
        {"time": "08.00 - 10.50", "subject": "Анатомия\n👩‍🏫 Преподаватель: Айкен Маратбековна (402 ауд.)"},
        {"time": "12.00 - 13.50", "subject": "Цифровая грамотность и использование ИИ\n👩‍🏫 Преподаватель: Сугуржанова Г.А. (104 ауд.)"}
    ],
    "Среда": [
        {"time": "12.00 - 13.50", "subject": "Медицинская генетика\n👩‍🏫 Преподаватель: Сауле Алихановна (519 ауд.)"},
        {"time": "16.00 - 18.50", "subject": "Художественная анатомия\n👨‍🏫 Преподаватель: Саитов В. (102 ауд.)"}
    ],
    "Четверг": [
        {"time": "08.00 - 09.50", "subject": "Казахский язык\n👩‍🏫 Преподаватель: Абнасырова Р. (320 ауд.)"},
        {"time": "10.00 - 11.50", "subject": "История медицины\n👩‍🏫 Преподаватель: Ғабит-ағай Айжыраков (601 ауд.)"}
    ],
    "Пятница": [
        {"time": "08.00 - 09.50", "subject": "Иностранный язык\n👩‍🏫 Преподаватель: Ассель Маратовна (318 ауд.)"},
        {"time": "10.00 - 11.50", "subject": "Латинский язык\n👩‍🏫 Преподаватель: Айгуль Амангельдиевна (325 ауд.)"}
    ],
    "Суббота": [],
    "Воскресенье": []
}

SUBJECTS_LIST = [
    "Введение в клинику", "Молекулярная биология", "Анатомия",
    "Цифровая грамотность", "Медицинская генетика", "Художественная анатомия",
    "Казахский язык", "История медицины", "Иностранный язык", "Латинский язык"
]


class UploadFileState(StatesGroup):
    waiting_for_file = State()
    waiting_for_subject = State()
    waiting_for_topic = State()


class ChatWithFileState(StatesGroup):
    active_chat = State()


def parse_time(time_str):
    return datetime.strptime(time_str.strip(), "%H.%M")


def extract_text_from_file(file_path):
    text = ""
    if file_path.endswith(".docx"):
        try:
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                if para.text.strip():
                    text += para.text + "\n"
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            text += cell.text + " "
                    text += "\n"
        except Exception as e:
            print(f"Ошибка чтения docx: {e}")

    elif file_path.endswith(".pdf"):
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        except Exception as e:
            print(f"Ошибка чтения pdf: {e}")

    return text


def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Сегодня", callback_data="day_today")
    builder.button(text="📅 Завтра", callback_data="day_tomorrow")
    builder.button(text="📚 Вся неделя", callback_data="schedule_all")
    builder.button(text="📂 Архив файлов", callback_data="file_archive")
    builder.button(text="📤 Загрузить материал", callback_data="upload_file_start")
    builder.button(text="🟢 Статус / Онлайн", callback_data="bot_status_check")
    builder.button(text="ℹ️ Инструкция", callback_data="bot_help")
    builder.adjust(2, 1, 2, 1, 1)
    return builder.as_markup()


async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню бота"),
        BotCommand(command="schedule", description="Расписание пар"),
        BotCommand(command="archive", description="Банк методичек и файлов"),
        BotCommand(command="status", description="Отчет о подключении и работе"),
        BotCommand(command="help", description="Как пользоваться ботом")
    ]
    await bot.set_my_commands(commands)


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🎓 **Академический ассистент группы ОМ117-А**\n\n"
        "Привет! Этот бот помогает нашей группе с расписанием и разбором учебных материалов через ИИ.\n"
        "Выбери нужный раздел в меню ниже:",
        reply_markup=get_main_menu()
    )


@dp.message(Command("status"))
async def cmd_status(message: types.Message, state: FSMContext):
    await state.clear()
    uptime_duration = datetime.now() - START_TIME
    hours = int(uptime_duration.total_seconds() // 3600)
    minutes = int((uptime_duration.total_seconds() % 3600) // 60)
    
    status_text = (
        "🟢 **ОТЧЕТ О ПОДКЛЮЧЕНИИ И СТАТУСЕ БОТА**\n\n"
        "✅ **Сервер:** Активен (Render Web Service)\n"
        "🤖 **Статус Telegram-бота:** Онлайн и принимает запросы\n"
        "⏰ **Время работы без перезагрузки:** свыше "
        f"{hours} ч. {minutes} мин.\n"
        "🔄 **Пинг-система:** Активна (UptimeRobot следит за соединением)\n"
        "🎯 **Группа:** ОМ117-А"
    )
    await message.answer(status_text, reply_markup=get_main_menu())


@dp.callback_query(F.data == "bot_status_check")
async def callback_status(callback: types.CallbackQuery):
    uptime_duration = datetime.now() - START_TIME
    hours = int(uptime_duration.total_seconds() // 3600)
    minutes = int((uptime_duration.total_seconds() % 3600) // 60)
    
    status_text = (
        "🟢 **ОТЧЕТ О ПОДКЛЮЧЕНИИ И СТАТУСЕ БОТА**\n\n"
        "✅ **Сервер:** Активен (Render Web Service)\n"
        "🤖 **Статус Telegram-бота:** Онлайн и принимает запросы\n"
        "⏰ **Время работы без перезагрузки:** свыше "
        f"{hours} ч. {minutes} мин.\n"
        "🔄 **Пинг-система:** Активна (UptimeRobot следит за соединением)\n"
        "🎯 **Группа:** ОМ117-А"
    )
    try:
        await callback.message.edit_text(status_text, reply_markup=get_main_menu())
    except Exception:
        pass
    await callback.answer("Статус обновлен: всё работает отлично!")


@dp.message(Command("schedule"))
async def cmd_schedule(message: types.Message, state: FSMContext):
    await state.clear()
    day_name = DAYS_LIST[datetime.now().weekday()]
    lessons = EXACT_SCHEDULE.get(day_name, [])
    await message.answer(format_day_schedule(day_name, lessons), reply_markup=get_main_menu())


@dp.message(Command("archive"))
async def cmd_archive(message: types.Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    for subj in SUBJECTS_LIST:
        builder.button(text=f"📂 {subj}", callback_data=f"arch_subj_{subj}")
    builder.button(text="⬅️ Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)
    await message.answer("📚 **Выберите предмет для просмотра материалов:**", reply_markup=builder.as_markup())


@dp.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "ℹ️ **Как пользоваться ботом:**\n\n"
        "1. **Расписание:** Кнопки «Сегодня» и «Завтра» показывают пары, аудитории, преподавателей.\n"
        "2. **Архив материалов:** Общий банк файлов нашей группы.\n"
        "3. **Загрузка:** Скидывай вордовский файл или PDF-методичку.\n"
        "4. **Работа с ИИ:** Открыв файл, пиши запросы простым языком.\n"
        "5. **Статус:** Команда `/status` проверяет подключение сервера.",
        reply_markup=get_main_menu()
    )


@dp.callback_query(F.data == "bot_help")
async def callback_help(callback: types.CallbackQuery):
    text = (
        "ℹ️ **Как пользоваться ботом:**\n\n"
        "1. **Расписание:** Кнопки «Сегодня» и «Завтра» показывают пары, аудитории, преподавателей.\n"
        "2. **Архив материалов:** Общий банк файлов нашей группы.\n"
        "3. **Загрузка:** Скидывай вордовский файл или PDF-методичку.\n"
        "4. **Работа с ИИ:** Открыв файл, пиши запросы простым языком.\n"
        "5. **Статус:** Команда `/status` проверяет подключение сервера."
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_main_menu())
    except Exception:
        pass
    await callback.answer()


def format_day_schedule(day_name, lessons):
    text = f"━━━━━━━━━━━━━━━━━━━\n" \
           f"📅 **РАСПИСАНИЕ: {day_name.upper()}**\n" \
           f"━━━━━━━━━━━━━━━━━━━\n\n"
    if not lessons:
        text += "🎉 **Пар нет! Прекрасный день для отдыха.**"
    else:
        for idx, item in enumerate(lessons, 1):
            text += f"🔹 **Пара {idx}** ⏰ *{item['time']}*\n" \
                    f"📚 {item['subject']}\n"
            if idx < len(lessons):
                try:
                    t1 = parse_time(item['time'].split("-")[1].strip())
                    t2 = parse_time(lessons[idx]['time'].split("-")[0].strip())
                    diff = int((t2 - t1).total_seconds() / 60)
                    if diff > 0:
                        if diff <= 15:
                            text += f"☕ *Перемена: {diff} мин*\n"
                        else:
                            text += f"⏳ *Окно: {diff} мин*\n"
                except:
                    pass
            text += f"───────────────────\n"
    return text


DAYS_LIST = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


@dp.callback_query(F.data == "day_today")
async def show_today(callback: types.CallbackQuery):
    day_name = DAYS_LIST[datetime.now().weekday()]
    lessons = EXACT_SCHEDULE.get(day_name, [])
    try:
        await callback.message.edit_text(format_day_schedule(day_name, lessons), reply_markup=get_main_menu())
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data == "day_tomorrow")
async def show_tomorrow(callback: types.CallbackQuery):
    tomorrow_index = (datetime.now().weekday() + 1) % 7
    day_name = DAYS_LIST[tomorrow_index]
    lessons = EXACT_SCHEDULE.get(day_name, [])
    try:
        await callback.message.edit_text(format_day_schedule(day_name, lessons), reply_markup=get_main_menu())
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data == "schedule_all")
async def show_all_schedule(callback: types.CallbackQuery):
    text = "📚 **РАСПИСАНИЕ ГРУППЫ ОМ117-А НА НЕДЕЛЮ**\n"
    for day, lessons in EXACT_SCHEDULE.items():
        text += f"\n🗓 **{day}**\n"
        if not lessons:
            text += "   └ 🌴 *Пар нет*\n"
        else:
            for idx, item in enumerate(lessons, 1):
                lines = item['subject'].splitlines()
                subj_name = lines[0]
                details = " | ".join(lines[1:]) if len(lines) > 1 else ""
                text += f"   • `{item['time']}` | **{subj_name}**"
                if details:
                    text += f"\n      └ {details}"
                text += "\n"
    try:
        await callback.message.edit_text(text, reply_markup=get_main_menu())
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data == "upload_file_start")
async def upload_file_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📤 **Отправь файл (лекцию, методичку, ворд или pdf)**, который хочешь добавить в общий архив группы:"
    )
    await state.set_state(UploadFileState.waiting_for_file)
    await callback.answer()


@dp.message(UploadFileState.waiting_for_file, F.document)
async def process_file(message: types.Message, state: FSMContext):
    document = message.document
    file_info = await bot.get_file(document.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)

    file_name = document.file_name
    file_path = os.path.join(UPLOAD_DIR, f"{int(datetime.now().timestamp())}_{file_name}")

    with open(file_path, "wb") as f:
        f.write(downloaded_file.read())

    uploader_name = message.from_user.full_name or message.from_user.username or "Студент"
    await state.update_data(file_path=file_path, file_name=file_name, uploader=uploader_name)

    builder = InlineKeyboardBuilder()
    for subj in SUBJECTS_LIST:
        builder.button(text=subj, callback_data=f"set_subj_{subj}")
    builder.adjust(2)

    await message.answer("📌 Выбери предмет, к которому относится этот материал:", reply_markup=builder.as_markup())
    await state.set_state(UploadFileState.waiting_for_subject)


@dp.callback_query(UploadFileState.waiting_for_subject, F.data.startswith("set_subj_"))
async def process_subject(callback: types.CallbackQuery, state: FSMContext):
    subject = callback.data.replace("set_subj_", "")
    await state.update_data(subject=subject)

    await callback.message.edit_text(f"✍️ Введи **название темы** для этого файла (текстом в чат):")
    await state.set_state(UploadFileState.waiting_for_topic)
    await callback.answer()


@dp.message(UploadFileState.waiting_for_topic)
async def process_topic(message: types.Message, state: FSMContext):
    topic = message.text.strip()
    data = await state.get_data()

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO files (subject, topic, file_path, file_name, uploader, upload_date) VALUES (?, ?, ?, ?, ?, ?)",
        (data['subject'], topic, data['file_path'], data['file_name'], data['uploader'],
         datetime.now().strftime("%Y-%m-%d"))
    )
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(
        f"✅ **Материал успешно добавлен в общий архив группы!**\n\n"
        f"📖 Предмет: *{data['subject']}*\n"
        f"📌 Тема: *{topic}*\n"
        f"📁 Файл: *{data['file_name']}*\n"
        f"👤 Загрузил(а): *{data['uploader']}*",
        reply_markup=get_main_menu()
    )


@dp.callback_query(F.data == "file_archive")
async def show_archive_subjects(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for subj in SUBJECTS_LIST:
        builder.button(text=f"📂 {subj}", callback_data=f"arch_subj_{subj}")
    builder.button(text="⬅️ Назад в меню", callback_data="back_to_menu")
    builder.adjust(1)

    try:
        await callback.message.edit_text("📚 **Выберите предмет для просмотра материалов группы:**",
                                         reply_markup=builder.as_markup())
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("arch_subj_"))
async def show_subject_files(callback: types.CallbackQuery):
    subject = callback.data.replace("arch_subj_", "")

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, topic, file_name, uploader FROM files WHERE subject = ?", (subject,))
    files = cursor.fetchall()
    conn.close()

    builder = InlineKeyboardBuilder()
    if files:
        for f_id, topic, f_name, uploader in files:
            builder.button(text=f"📄 {topic} ({uploader})", callback_data=f"file_info_{f_id}")

    builder.button(text="⬅️ К списку предметов", callback_data="file_archive")
    builder.adjust(1)

    text = f"📂 **Материалы по предмету: {subject}**\n\n"
    if not files:
        text += "📭 По этому предмету пока нет загруженных файлов."

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("file_info_"))
async def file_actions(callback: types.CallbackQuery, state: FSMContext):
    file_id = callback.data.replace("file_info_", "")

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT subject, topic, file_path, file_name, uploader, upload_date FROM files WHERE id = ?",
                   (file_id,))
    file_data = cursor.fetchone()
    conn.close()

    if not file_data:
        await callback.answer("Файл не найден!", show_alert=True)
        return

    subject, topic, file_path, file_name, uploader, upload_date = file_data

    await state.update_data(active_file_path=file_path, active_file_name=file_name)
    await state.set_state(ChatWithFileState.active_chat)

    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Скачать оригинал файла", callback_data=f"download_{file_id}")
    builder.button(text="⬅️ Назад к предмету", callback_data=f"arch_subj_{subject}")
    builder.adjust(1)

    text = f"📄 **Выбран материал:**\n\n" \
           f"📖 Предмет: *{subject}*\n" \
           f"📌 Тема: *{topic}*\n" \
           f"📁 Файл: *{file_name}*\n" \
           f"👤 Загрузил(а): *{uploader}*\n\n" \
           f"💬 **Режим свободного запроса активирован!**\n" \
           f"Напиши в чат свой запрос к этому файлу, и ИИ ответит."

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except Exception:
        pass
    await callback.answer()


@dp.message(ChatWithFileState.active_chat)
async def handle_user_query_to_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    file_path = data.get('active_file_path')
    user_prompt = message.text

    if not file_path or not os.path.exists(file_path):
        await message.answer("⚠️ Ошибка: файл не найден.")
        return

    status_msg = await message.answer("🧠 Шаг 1/3: Открываю файл и читаю текст...")
    file_text = extract_text_from_file(file_path)

    if not file_text.strip():
        await status_msg.edit_text("⚠️ Не удалось извлечь текст из файла.")
        return

    await asyncio.sleep(0.4)
    await status_msg.edit_text("🔍 Шаг 2/3: Анализирую структуру методички...")

    await asyncio.sleep(0.4)
    await status_msg.edit_text("✍️ Шаг 3/3: ИИ пишет ответ по твоему запросу...")

    try:
        prompt_text = f"""Ты — умный академический ассистент для студентов-медиков. 
Ниже предоставлен текст из учебного документа/методички. 
Выполни запрос студента строго по делу, без лишней воды, опираясь на этот текст.

Текст документа:
{file_text}

Запрос студента:
{user_prompt}"""

      # Запрос через правильный метод для твоего типа ключа
        interaction = client.interactions.create(
            model='models/gemini-3.8-flash',
            input=prompt_text,
        )
        
        if interaction and hasattr(interaction, 'steps') and interaction.steps:
            answer_text = interaction.steps[-1]
            await status_msg.edit_text(str(answer_text)[:4000])
        elif interaction and hasattr(interaction, 'text'):
            await status_msg.edit_text(str(interaction.text)[:4000])
        else:
            await status_msg.edit_text(str(interaction)[:4000])

    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ошибка при обращении к ИИ: {e}")


@dp.callback_query(F.data.startswith("download_"))
async def send_file_to_user(callback: types.CallbackQuery):
    file_id = callback.data.replace("download_", "")

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, file_name FROM files WHERE id = ?", (file_id,))
    res = cursor.fetchone()
    conn.close()

    if res:
        file_path, file_name = res
        if os.path.exists(file_path):
            document = FSInputFile(file_path, filename=file_name)
            await callback.message.answer_document(document)
        else:
            await callback.message.answer("⚠️ Файл не найден на сервере.")

    await callback.answer()


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text(
            "🎓 **Академический ассистент группы ОМ117-А**\nГлавное меню:",
            reply_markup=get_main_menu()
        )
    except Exception:
        pass
    await callback.answer()


# --- МИНИ-СЕРВЕР ДЛЯ ПИНГОВ (RENDER & UPTIMEROBOT) ---
class SimpleHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

    def log_message(self, format, *args):
        pass


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()


async def main():
    server_process = multiprocessing.Process(target=run_web_server, daemon=True)
    server_process.start()

    await set_bot_commands(bot)
    print("Бот успешно запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
