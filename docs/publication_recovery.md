# Захист публікації від аварій

Журнал `stage3.publication_attempts` використовує ключі `telegram:{content_version}`
і `knowledge_base:{content_version}`. Кожна спроба має UUID, хеш точного тексту,
призначення, час початку, результат та записи в history. SQL-міграція не потрібна.

Перед зовнішнім API під блокуванням рядка записується SENDING і виконується commit.
Повторний callback бачить цей запис і не відправляє матеріал знову. Після API сервіс
повторно блокує рядок, перевіряє ID спроби й редакцію та атомарно записує SUCCEEDED
разом із зовнішнім ID і статусом публікації. Успіх і явна відмова також мають commit,
незалежний від наступної транзакції Бази чи завершення webhook.

Явна відмова провайдера без створення публікації (`PublicationRejected`) → FAILED,
retry дозволено. Timeout, 5xx, втрачена/некоректна відповідь або невідомий виняток
після зовнішнього виклику → UNKNOWN. Завершення процесу лишає SENDING. Обидва стани
блокують повторне відправлення, редагування та зміну рішення для цієї редакції.
Статус Telegram у review API/модерації: RECONCILIATION_REQUIRED. Невизначеність Бази
не скасовує Telegram PUBLISHED. Незавершені спроби не мають автоматичного timeout-reset.

## Ручна звірка

1. Зупинити попередній worker/процес, щоб він не продовжив відправлення після звірки.
2. Перевірити цільовий Telegram-канал або знайти Notion-сторінку за «Ключ редакції».
   Ключ Notion: SHA-256 від `document_id:version_id:content_version`.
3. Якщо результат ще не можна достовірно встановити, нічого не скидати.
4. У конфігурації задати окремий PUBLICATION_RECOVERY_SECRET; передавати його лише
   заголовком X-Publication-Recovery-Secret. Без налаштування endpoint закритий (503),
   неправильний секрет → 403. Секрет приховується logging formatter.
5. Викликати POST `/review/items/{version_id}/recover-publication` з полями:
   target (`telegram` / `knowledge_base`), content_version, attempt_id, outcome
   (`PUBLISHED` / `NOT_PUBLISHED`), note (опис перевірки, мінімум 10 знаків),
   previous_worker_stopped=true. Для PUBLISHED обов’язковий reference_id
   (Telegram message ID / Notion page ID); для Бази можна передати page_url.

SENDING можна звірити не раніше 5 хвилин від початку. Це лише додатковий захист:
попередній worker має бути зупинений незалежно від віку спроби.
PUBLISHED фіксує знайдений зовнішній ID без повторного API-виклику.
NOT_PUBLISHED дозволяє наступну явну дію користувача; сама звірка нічого не публікує.
ID спроби та редакції перевіряються, повторна звірка завершеної спроби повертає 409.
Звірка зберігається в history. API покладається на фактичну перевірку оператором;
Telegram Bot API не дає надійно знайти втрачений sendMessage за нашим внутрішнім UUID.

Захист забезпечує відсутність автоматичної повторної доставки при невизначеності,
але не гарантує автоматичне завершення кожної доставки або математичний exactly-once
для зовнішніх API. Якщо процес впав до фактичного відправлення, SENDING теж потребує
звірки. SQLite не має PostgreSQL row locks; багатопроцесна production-публікація
потребує PostgreSQL. Приватні moderation cards і службові відповіді не входять
до цього журналу; захищені публікації каналу та Бази знань.

Змінено: ReviewService, TelegramWorkflowService, publisher, schemas, knowledge-base
service/errors, Notion adapter, review API, config/logging, .env.example та тести.

Перевірки 21.09.2026: **142 passed, 0 skipped**, включно з PostgreSQL-specific
перевірками проти окремої бази `legal_monitoring_test`; compileall — успішно.
Recovery secret налаштовано локально без виведення значення.
Журнал застосовується у ReviewService; прямі adapter-виклики, зокрема окремий acceptance
smoke-скрипт, не мають цього durable marker і не є production-шляхом публікації.
