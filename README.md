# 🚀 Doc-to-Content

Превращает документы (PDF, DOCX, PPTX) в готовый контент за секунды.

---

## ⚡ Что делает

На вход:

* PDF
* презентация
* документ

На выход:

* 📄 Summary
* 📝 Статья
* 📢 Посты для Telegram
* ❓ FAQ
* 📘 Markdown

---

## 🔥 Как это работает

1. Загружаешь файл
2. Выбираешь режим
3. Получаешь готовый контент

---

## 🧠 Режимы обработки

* **RAW** — как есть
* **CLEAN** — очистка текста
* **AI** — генерация через модель

---

## 🤖 Telegram бот

Бот принимает файл и возвращает результат.

### Команды:

* `/start` — запуск
* `/mode` — режим (AI / CLEAN / RAW)
* `/preset` — тип пакета (single / creator / knowledge)
* `/result` — формат результата
* `/status` — текущие настройки

---

## 💻 Запуск

### Установка зависимостей

```bash
pip install -r requirements.txt
```

---

### Запуск GUI

```bash
python pdf_md_gui.py
```

---

### Запуск Telegram бота

```bash
python telegram_bot_mvp.py
```

---

## ⚙️ Настройки

Используются переменные окружения:

```bash
TELEGRAM_BOT_TOKEN=your_token
OPENROUTER_API_KEY=your_api_key
```

---

## 📦 Пример

📥 Вход:
PDF / презентация

📤 Выход:

* summary
* посты
* статья

---

## 🛠 Стек

* Python
* CustomTkinter
* Telegram Bot API
* OpenRouter

---

## 👨‍💻 Автор

Egor
