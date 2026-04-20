#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram Bot v7 for Doc-to-Content

Что внутри:
- человеческий UX без технических слов
- быстрые сценарии: быстрое summary / умное summary / посты / статья / FAQ / markdown
- inline-кнопки и меню
- статус текущего режима
- прогресс-сообщения пользователю
- защита от слишком больших файлов
- zip-архив результата
- fallback на CLEAN, если AI недоступен
- white-list пользователей (опционально)
- лимиты на пользователя в день
- JSON-база пользователей
- премиум-доступ через админ-команду

Требует рядом файл pdf_md_gui.py
Из него импортируются: CoreService, build_jobs_from_args, zip_directory

Установка:
    py -m pip install python-telegram-bot==21.6 requests pymupdf python-docx python-pptx beautifulsoup4 markdownify customtkinter

Переменные окружения:
    TELEGRAM_BOT_TOKEN=...
    OPENROUTER_API_KEY=...

Опционально:
    ALLOWED_TELEGRAM_USER_IDS=123,456
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from pdf_md_gui import CoreService, build_jobs_from_args, zip_directory


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("doc_to_content_bot")

SUPPORTED_EXTS = {".pdf", ".docx", ".pptx", ".html", ".htm"}
DEFAULT_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"
DEFAULT_OUTPUT_DIR = "output"
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
FALLBACK_TO_CLEAN = True

USERS_DB = Path("users_db.json")
FREE_DAILY_LIMIT = 3

# ВСТАВЬ СЮДА СВОЙ TELEGRAM USER ID
ADMIN_IDS = {
    123456789,
}


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    mode: str
    preset: str
    result: str
    description: str


SCENARIOS: dict[str, Scenario] = {
    "fast_summary": Scenario(
        key="fast_summary",
        title="Быстрое summary",
        mode="CLEAN",
        preset="single",
        result="summary",
        description="Быстро, без AI. Подходит для чернового конспекта.",
    ),
    "smart_summary": Scenario(
        key="smart_summary",
        title="Умное summary",
        mode="AI",
        preset="single",
        result="summary",
        description="Медленнее, но обычно заметно качественнее.",
    ),
    "posts": Scenario(
        key="posts",
        title="Посты",
        mode="AI",
        preset="single",
        result="posts",
        description="5–10 готовых постов для Telegram.",
    ),
    "article": Scenario(
        key="article",
        title="Статья",
        mode="AI",
        preset="single",
        result="article",
        description="Полноценный текст с нормальной структурой.",
    ),
    "faq": Scenario(
        key="faq",
        title="FAQ",
        mode="AI",
        preset="single",
        result="faq",
        description="Вопросы-ответы по материалу.",
    ),
    "markdown": Scenario(
        key="markdown",
        title="Markdown",
        mode="CLEAN",
        preset="single",
        result="markdown",
        description="Быстрый структурированный текст без AI.",
    ),
    "creator_pack": Scenario(
        key="creator_pack",
        title="Creator Pack",
        mode="AI",
        preset="creator",
        result="summary",
        description="Summary + article + posts одним архивом.",
    ),
    "knowledge_pack": Scenario(
        key="knowledge_pack",
        title="Knowledge Pack",
        mode="AI",
        preset="knowledge",
        result="summary",
        description="Summary + FAQ + markdown.",
    ),
}

DEFAULT_SCENARIO_KEY = "smart_summary"


def load_users() -> dict[str, Any]:
    if USERS_DB.exists():
        try:
            return json.loads(USERS_DB.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_users(data: dict[str, Any]) -> None:
    USERS_DB.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_user_record(user_id: int | str) -> dict[str, Any]:
    users = load_users()
    return users.get(
        str(user_id),
        {
            "used_today": 0,
            "last_date": "",
            "is_premium": False,
        },
    )


def update_user_record(user_id: int | str, record: dict[str, Any]) -> None:
    users = load_users()
    users[str(user_id)] = record
    save_users(users)


def check_limit(user_id: int) -> tuple[bool, dict[str, Any]]:
    record = get_user_record(user_id)
    today = datetime.now().strftime("%Y-%m-%d")

    if record["last_date"] != today:
        record["used_today"] = 0
        record["last_date"] = today
        update_user_record(user_id, record)

    if record["is_premium"]:
        return True, record

    if record["used_today"] >= FREE_DAILY_LIMIT:
        return False, record

    return True, record


def increment_usage(user_id: int) -> None:
    record = get_user_record(user_id)
    today = datetime.now().strftime("%Y-%m-%d")

    if record["last_date"] != today:
        record["used_today"] = 0
        record["last_date"] = today

    record["used_today"] += 1
    update_user_record(user_id, record)


def allowed_user_ids() -> set[int]:
    raw = os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "").strip()
    if not raw:
        return set()

    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids


def is_allowed(update: Update) -> bool:
    whitelist = allowed_user_ids()
    if not whitelist:
        return True
    user = update.effective_user
    return bool(user and user.id in whitelist)


def get_user_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    data = context.user_data
    data.setdefault("scenario", DEFAULT_SCENARIO_KEY)
    return data


def get_scenario(context: ContextTypes.DEFAULT_TYPE) -> Scenario:
    state = get_user_state(context)
    key = state.get("scenario", DEFAULT_SCENARIO_KEY)
    return SCENARIOS.get(key, SCENARIOS[DEFAULT_SCENARIO_KEY])


def render_scenario(s: Scenario) -> str:
    return (
        f"Режим: {s.title}\n"
        f"mode={s.mode} | preset={s.preset} | result={s.result}\n"
        f"{s.description}"
    )


def root_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("⚡ Быстрое summary", callback_data="scenario:fast_summary"),
            InlineKeyboardButton("🧠 Умное summary", callback_data="scenario:smart_summary"),
        ],
        [
            InlineKeyboardButton("✍️ Статья", callback_data="scenario:article"),
            InlineKeyboardButton("📮 Посты", callback_data="scenario:posts"),
        ],
        [
            InlineKeyboardButton("❓ FAQ", callback_data="scenario:faq"),
            InlineKeyboardButton("📝 Markdown", callback_data="scenario:markdown"),
        ],
        [
            InlineKeyboardButton("🎁 Creator Pack", callback_data="scenario:creator_pack"),
            InlineKeyboardButton("📚 Knowledge Pack", callback_data="scenario:knowledge_pack"),
        ],
        [
            InlineKeyboardButton("ℹ️ Текущий режим", callback_data="menu:status"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def ensure_allowed(update: Update) -> bool:
    if is_allowed(update):
        return True

    target = update.effective_message
    if target:
        await target.reply_text("Этот бот сейчас работает в закрытом режиме.")
    return False


async def send_home(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    scenario = get_scenario(context)
    text = (
        "Превращаю документы в готовый результат.\n\n"
        "Что можно сделать:\n"
        "— быстрое summary\n"
        "— умное summary\n"
        "— посты\n"
        "— статью\n"
        "— FAQ\n"
        "— markdown\n"
        "— creator pack\n"
        "— knowledge pack\n\n"
        f"Сейчас выбран режим:\n{render_scenario(scenario)}\n\n"
        "Выбери сценарий кнопками ниже или просто отправь файл."
    )
    await message.reply_text(text, reply_markup=root_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    await send_home(update.message, context)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    await send_home(update.message, context)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    await send_home(update.message, context)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    scenario = get_scenario(context)
    await update.message.reply_text(render_scenario(scenario), reply_markup=root_keyboard())


async def give_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return

    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("Недостаточно прав.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /premium USER_ID")
        return

    target_id = context.args[0]
    record = get_user_record(target_id)
    record["is_premium"] = True
    update_user_record(target_id, record)

    await update.message.reply_text(f"Пользователь {target_id} теперь premium.")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return

    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("Недостаточно прав.")
        return

    users = load_users()
    total = len(users)
    premium = sum(1 for x in users.values() if x.get("is_premium"))
    today = datetime.now().strftime("%Y-%m-%d")
    used_today = sum(
        int(x.get("used_today", 0))
        for x in users.values()
        if x.get("last_date") == today
    )

    await update.message.reply_text(
        f"Статистика:\n"
        f"— пользователей: {total}\n"
        f"— premium: {premium}\n"
        f"— использований сегодня: {used_today}"
    )


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return

    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "menu:status":
        scenario = get_scenario(context)
        await query.edit_message_text(
            f"Сейчас выбран режим:\n\n{render_scenario(scenario)}",
            reply_markup=root_keyboard(),
        )
        return

    if data.startswith("scenario:"):
        scenario_key = data.split(":", 1)[1]
        if scenario_key not in SCENARIOS:
            await query.edit_message_text("Неизвестный сценарий.", reply_markup=root_keyboard())
            return

        context.user_data["scenario"] = scenario_key
        scenario = SCENARIOS[scenario_key]

        await query.edit_message_text(
            f"Ок, выбран режим:\n\n{render_scenario(scenario)}\n\nТеперь просто отправь файл.",
            reply_markup=root_keyboard(),
        )
        return


async def quick_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    context.user_data["scenario"] = "smart_summary"
    await update.message.reply_text(
        "Ок, включил режим: Умное summary. Теперь отправь файл.",
        reply_markup=root_keyboard(),
    )


async def quick_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    context.user_data["scenario"] = "posts"
    await update.message.reply_text(
        "Ок, включил режим: Посты. Теперь отправь файл.",
        reply_markup=root_keyboard(),
    )


async def quick_article(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    context.user_data["scenario"] = "article"
    await update.message.reply_text(
        "Ок, включил режим: Статья. Теперь отправь файл.",
        reply_markup=root_keyboard(),
    )


async def quick_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    context.user_data["scenario"] = "faq"
    await update.message.reply_text(
        "Ок, включил режим: FAQ. Теперь отправь файл.",
        reply_markup=root_keyboard(),
    )


def build_service(client_name: str, scenario: Scenario) -> CoreService:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    return CoreService(
        process_mode=scenario.mode,
        client_name=client_name,
        output_folder_name=DEFAULT_OUTPUT_DIR,
        use_output_folder=True,
        copy_source=True,
        api_url=DEFAULT_API_URL,
        api_key=api_key,
        model_name=DEFAULT_MODEL,
        ai_preclean=True,
        logger=lambda msg: logger.info(msg),
    )


def process_document_blocking(src_path: Path, scenario: Scenario, chat_id: int) -> Path:
    jobs = build_jobs_from_args(scenario.preset, scenario.result)
    service = build_service(f"tg_{chat_id}", scenario)

    try:
        out_dir = service.process_file(src_path, jobs)
    except Exception:
        if scenario.mode == "AI" and FALLBACK_TO_CLEAN:
            logger.warning("AI failed, fallback to CLEAN")
            fallback = Scenario(
                key=scenario.key,
                title=scenario.title + " (fallback CLEAN)",
                mode="CLEAN",
                preset=scenario.preset,
                result=scenario.result,
                description=scenario.description,
            )
            out_dir = build_service(f"tg_{chat_id}", fallback).process_file(src_path, jobs)
        else:
            raise

    zip_path = out_dir.with_suffix(".zip")
    zip_directory(out_dir, zip_path)
    return zip_path


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return

    message = update.message
    if not message or not message.document:
        return

    user = update.effective_user
    if not user:
        await message.reply_text("Не удалось определить пользователя.")
        return

    ok, record = check_limit(user.id)
    if not ok:
        await message.reply_text(
            "Лимит на сегодня закончился.\n\n"
            "Если хочешь доступ без ограничений — напиши мне."
        )
        return

    document = message.document
    filename = document.file_name or "document.bin"
    ext = Path(filename).suffix.lower()
    scenario = get_scenario(context)

    if ext not in SUPPORTED_EXTS:
        await message.reply_text("Этот формат пока не поддерживается. Нужны pdf/docx/pptx/html.")
        return

    if document.file_size and document.file_size > MAX_FILE_SIZE_BYTES:
        await message.reply_text(f"Файл слишком большой. Сейчас лимит — {MAX_FILE_SIZE_MB} MB.")
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)

    waiting_text = (
        f"Файл получил: {filename}\n\n"
        f"Режим: {scenario.title}\n"
        f"{scenario.description}\n\n"
    )
    if scenario.mode == "AI":
        waiting_text += "AI-обработка может занять 1–3 минуты."
    else:
        waiting_text += "Быстрый режим, обычно это занимает совсем немного времени."

    status_msg = await message.reply_text(waiting_text)

    with tempfile.TemporaryDirectory(prefix="doc_to_content_bot_") as tmpdir:
        tmp_path = Path(tmpdir)
        local_file = tmp_path / filename

        file_obj = await context.bot.get_file(document.file_id)
        await file_obj.download_to_drive(custom_path=str(local_file))

        try:
            await status_msg.edit_text("Файл скачал. Вытаскиваю и обрабатываю текст...")
            zip_path = await asyncio.to_thread(process_document_blocking, local_file, scenario, message.chat_id)

            increment_usage(user.id)

            await status_msg.edit_text("Готово. Отправляю архив.")
            with open(zip_path, "rb") as f:
                await message.reply_document(
                    document=f,
                    filename=zip_path.name,
                    caption=(
                        "Готово.\n"
                        f"Сценарий: {scenario.title}\n"
                        f"Осталось бесплатных запусков сегодня: "
                        f"{max(0, FREE_DAILY_LIMIT - get_user_record(user.id).get('used_today', 0))}"
                        if not get_user_record(user.id).get("is_premium")
                        else f"Готово.\nСценарий: {scenario.title}\nPremium доступ активен"
                    ),
                )
        except Exception as exc:
            logger.exception("Processing failed")
            await status_msg.edit_text(f"Ошибка обработки: {exc}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    if update.message:
        await update.message.reply_text(
            "Просто отправь файл или выбери режим кнопками ниже.",
            reply_markup=root_keyboard(),
        )


async def post_init(app: Application) -> None:
    logger.info("Telegram bot started")


def build_app(token: str) -> Application:
    return (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("summary", quick_summary))
    app.add_handler(CommandHandler("posts", quick_posts))
    app.add_handler(CommandHandler("article", quick_article))
    app.add_handler(CommandHandler("faq", quick_faq))
    app.add_handler(CommandHandler("premium", give_premium))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в переменных окружения")

    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        logger.warning("OPENROUTER_API_KEY пустой. AI режим может не сработать.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = build_app(token)
    register_handlers(app)
    app.run_polling()


if __name__ == "__main__":
    main()