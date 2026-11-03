# Развёртывание в Yandex Cloud

Бот работает как Cloud Function (Python 3.12) за API Gateway; модель — Alice AI LLM Flash
в Yandex AI Studio. Ключи не нужны: функция ходит в модель от имени сервисного аккаунта
(IAM-токен берётся у metadata-сервиса, см. `_yandex_chat` в `backend/llm.py`).

## Что создано (каталог `default`, облако cloud-agrospublic)

| Ресурс | Имя | Назначение |
|---|---|---|
| Object Storage | `agravia-alisa-deploy` | хранит zip с кодом (>3,5 МБ нельзя загрузить в функцию напрямую) |
| Cloud Function | `agravia-alisa-bot` (public, 512 МБ, 30 с) | FastAPI-бэкенд, entrypoint `yc_entry.handler` |
| API Gateway | `agravia-alisa-gw` | даёт функции подпути (`/api/chat`, `/widget/widget.js`) |

Адрес бота: `https://d5daon1oep4l58a9tuca.jki8ffxa.apigw.yandexcloud.net`
(виджет: `/widget/widget.js`, чат: `POST /api/chat`, проверка: `GET /api/health`).

Переменные окружения функции: `LLM_PROVIDER=yandex`, `YANDEX_FOLDER_ID`, `YANDEX_MODEL`
(`gpt://<folder_id>/aliceai-llm-flash/latest`). Сервисный аккаунт функции должен иметь роль
`ai.languageModels.user` (сейчас привязан `ai-studio-25909e` с `ai.editor`).

## Как выкатить новую версию

```bash
python -I deploy/yandex/build_zip.py          # соберёт deploy/yandex/dist/agravia-bot.zip
```
1. Загрузите zip в бакет под новым именем (например `agravia-bot-v3.zip`).
2. Функция → Редактор → источник «Object Storage» → укажите новый объект → «Сохранить изменения».

Файлы: `yc_entry.py` — мост событие Cloud Functions → ASGI; `build_zip.py` — сборка архива
с зависимостями под Linux x86_64 / Python 3.12.

## Ограничения
- Логи диалогов пишутся в `/tmp` функции и не сохраняются между вызовами (как и на Vercel).
- Передача менеджеру (handoff) по-прежнему требует `TELEGRAM_*` или `HANDOFF_WEBHOOK_URL`.
- Холодный старт функции добавляет 1–3 с к первому ответу.
