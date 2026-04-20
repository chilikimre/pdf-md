# Doc-to-Content

Конвертирует документы (PDF, DOCX, PPTX) в готовый контент.

## Возможности

* Summary документа
* Статья
* Посты для Telegram
* FAQ
* Markdown

## Как использовать

### GUI

```bash
python pdf_md_gui.py
```

### Telegram бот

```bash
python telegram_bot_mvp.py
```

## Настройки

Использует переменные окружения:

```bash
TELEGRAM_BOT_TOKEN=your_token
OPENROUTER_API_KEY=your_key
```

## Режимы

* RAW — как есть
* CLEAN — очистка текста
* AI — генерация через модель

## Пример

Загружаешь файл → получаешь:

* summary
* посты
* статью

## Стек

* Python
* CustomTkinter
* Telegram Bot API
* OpenRouter

## Автор

Egor
