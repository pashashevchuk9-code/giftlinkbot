# Деплой на Render (бесплатный план)

Бот работает по long polling и одновременно поднимает HTTP-сервер на порту
`PORT`, который Render выдаёт автоматически. Health-check: `/health`.

## Что важно знать про бесплатный план

1. **Render Free — это Web Service.** Background Worker на бесплатном плане
   недоступен, поэтому бот запускается как web-сервис с health-сервером.
2. **Сервис засыпает после ~15 минут без входящих HTTP-запросов.** Пока
   сервис спит, бот не получает сообщения. Нужен внешний пинг `/health`
   каждые 5–10 минут (UptimeRobot, cron-job.org и т.п.).
3. **Диск эфемерный.** SQLite-файл (`data/nft_offers.sqlite3`) удаляется при
   каждом деплое и перезапуске контейнера. Для постоянного хранения нужен
   платный Persistent Disk либо внешняя БД (PostgreSQL). Пока используйте
   `/backup` перед деплоем.
4. **750 инстанс-часов в месяц.** Один постоянно работающий сервис съедает
   почти весь лимит.

## Шаг 1. Репозиторий

```powershell
cd C:\Users\PC\Desktop\1112
git init
git add .
git commit -m "GiftIinkBot with roles, menu and Render deployment"
git remote add origin https://github.com/ВАШ_АККАУНТ/giftlinkbot.git
git push -u origin main
```

`.env` в репозиторий не попадает (он в `.gitignore`).

## Шаг 2. Blueprint в Render

1. Зайдите на https://dashboard.render.com → **New** → **Blueprint**.
2. Подключите GitHub-репозиторий.
3. Render прочитает `render.yaml` и создаст Web Service `giftlinkbot`.
4. В поле **BOT_TOKEN** вставьте токен из BotFather (значение `sync: false`
   Render спросит при создании).
5. Нажмите **Apply**. Дождитесь статуса **Live**.

## Шаг 3. Проверка

- `https://giftlinkbot.onrender.com/health` → `{"status": "ok", ...}`
- В логах Render: `HTTP health-сервер слушает порт ...`,
  `Подключение к Telegram проверено`, `Бот запущен`.
- В Telegram: `/start`, `/whoami`, `/comand`, `/admins`.
- Владелец `5809580581` должен получить роль OWNER автоматически при первом
  действии (или после перезапуска, если запись уже есть в БД).
- Выдача ролей: `/roles @username ADMIN` (доступно только OWNER).

## Важно: один токен — один процесс

Перед запуском на Render остановите локального бота, иначе Telegram вернёт
ошибку конфликта long polling (оба процесса будут забирать одни и те же
обновления):

```powershell
cd C:\Users\PC\Desktop\1112
.\stop_24_7.bat
```

Вернуть локальный запуск: `.\install_24_7_user.bat`.

## Шаг 4. Не давать сервису засыпать

Создайте бесплатный монитор на https://uptimerobot.com:

- тип: **HTTP(s)**
- URL: `https://ИМЯ-СЕРВИСА.onrender.com/health`
- интервал: **5 минут**

Либо cron-job.org с тем же URL.

## Шаг 5. Обновления

```powershell
git add .
git commit -m "update"
git push
```

Render пересоберёт сервис автоматически (`autoDeploy: true`).

## Ограничения, которые нельзя обойти на Free

- Нельзя подключить постоянный диск → база обнуляется при рестарте.
- Нельзя запустить background worker → используется web service + пинг.
- Если пинг прекратится, бот уснёт и перестанет отвечать в Telegram.

Для стабильной работы 24/7 без засыпания нужен платный план Render
(Starter + Persistent Disk) либо VPS. Локальный запуск на вашем ПК уже
настроен через задачу `GiftIinkBot`.
