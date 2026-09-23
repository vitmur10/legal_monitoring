# Stage 4 — База знань

Stage 1: adapters → normalization → identity → immutable document versions.
Stage 2: diff → relevance → structured analysis → content generation.
UNCHANGED не запускає AI; FILTERED_OUT зберігає relevance.reason і результат у metadata
та історії monitoring run. Stage 3/4 приймають лише ANALYZED.

Кнопки «📢 Telegram» і «📚 Telegram + База» погоджують поточну редакцію з явним вибором
призначення. Telegram отримує тільки telegram_post. Повна стаття доступна в приватній
модерації та публікується через KnowledgeBaseService → adapter.
AI повертає knowledge_base_recommendation як об’єкт recommendation, reason, confidence;
рекомендація не запускає публікацію автоматично.

«📚 Додати в Базу» та POST /review/items/{version_id}/knowledge-base додають вже
погоджений Telegram-матеріал без повторного виклику Telegram publisher.
Для POST /review/items/{version_id}/publish можна передати include_knowledge_base=true.
dry_run не змінює статус публікації та не викликає Базу.

Публікації Бази зберігаються у stage3.knowledge_base_publications за content_version.
SQL-міграція не потрібна. Попередній stage3.notion читається для відповідної редакції.
Кожна нова погоджена редакція має окремий ключ document_id:version_id:content_version,
нову сторінку та previous_page_id. Старі сторінки не видаляються.
Перед створенням Notion adapter шукає сторінку за «Ключ редакції».
POST /pages не повторюється автоматично при мережевій помилці. Невизначений результат
блокує нове створення до звірки; безпечний retry після явної відмови спочатку шукає
наявну сторінку. Успіх Telegram фіксується в БД перед викликом Бази.
Блокування рядка PostgreSQL і оновлення ORM-стану захищають одночасні callback.
Це не гарантія exactly-once при аварії процесу між зовнішнім API та записом у БД:
Telegram sendMessage не підтримує ідемпотентний ключ, а Notion не має унікального
обмеження на користувацьке поле. Durable SENDING до виклику API запобігає автоматичній
повторній доставці після аварії. Правила звірки описані в [publication_recovery.md](publication_recovery.md).

Notion MVP використовує одну налаштовану базу «TaxSignal UA | База знань».
На Notion API 2025-09-03+ змінна `NOTION_DATABASE_ID` містить ID основного data source
цієї бази; назву змінної збережено для сумісності конфігурації.
ensure_database_schema — явна операція налаштування: додає українські поля і перевіряє
типи; звичайний pipeline не змінює схему. Додаткові технічні українські поля:
«Ідентифікатор документа», «Ключ редакції», «Повідомлення Telegram», «Попередня редакція».
NOTION_PROPERTY_MAP може перевизначити назви полів. Токен і database ID беруться з env.

Запуск acceptance smoke: python scripts/notion_live_smoke.py.
Він отримує саме ЗІР 41820, використовує погоджений контент за наявності або справжній
офіційний текст як smoke-статтю, створює одну сторінку і перевіряє повторний виклик.
Smoke не запускає AI/Telegram та не підробляє статус погодження. Результат пишеться
окремо в stage4_smoke. Без NOTION_TOKEN або NOTION_DATABASE_ID скрипт повідомляє
конкретні відсутні параметри. Для живої БД потрібні DATABASE_URL та Stage 1 міграції.

## Змінені файли

- `app/knowledge_base/__init__.py`, `service.py`, `labels.py` — новий контракт і українські значення.
- `app/ai/schemas.py`, `analysis_service.py`, `content_service.py`, `prompts.py` — рекомендації та експрес-аналіз.
- `app/stage3/review_service.py`, `telegram_service.py`, `publisher.py`, `schemas.py`, `factory.py` — вибір призначення, пізніше додавання, незалежний retry.
- `app/notion/client.py` — українські поля, ключ редакції, налаштування схеми.
- `app/repositories/document_repository.py` — оновлення ORM-стану під блокуванням.
- `app/api/routes/review.py` — endpoint Бази та обробка заборони публікації.
- `app/core/logging.py` — приховування секретів у повідомленнях і traceback.
- `scripts/notion_live_smoke.py` — acceptance ЗІР 41820.
- `tests/unit/test_stage4_knowledge_base.py`, `tests/integration/test_stage4_publication.py` — нові перевірки.
- `tests/unit/test_ai_content_service.py`, `test_stage3_review_service.py`, `test_stage3_telegram_workflow.py`, `tests/integration/test_review_api.py` — актуалізація очікувань.
- `docs/architecture.md`, `docs/stage4.md` — документація.

## Перевірки 21.09.2026

- pytest: **142 passed, 0 skipped**, включно з PostgreSQL-specific тестами проти
  ізольованої локальної бази `legal_monitoring_test`.
- compileall для app/scripts/tests: успішно.
- Live smoke ЗІР 41820: **успішно** — `first=PUBLISHED`, `repeat=PUBLISHED`,
  `same_page=True`; створено одну сторінку без дубля.
- Notion adapter використовує API `2026-03-11` і data-source endpoints.
- `PUBLICATION_RECOVERY_SECRET` згенеровано та налаштовано локально; значення не
  виводилося в чат або логи.
- git diff --check: недоступно, каталог не є Git-репозиторієм.
