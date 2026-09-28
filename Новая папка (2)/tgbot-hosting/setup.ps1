$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

function Pause-Exit($code = 0) { Read-Host "Нажмите Enter для выхода" | Out-Null; exit $code }

Write-Host ""
Write-Host "=== Установка Bot Hosting ===" -ForegroundColor Cyan
Write-Host ""

# 1. Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker не найден. Открываю страницу загрузки Docker Desktop..." -ForegroundColor Yellow
    Write-Host "Установите его, перезагрузите компьютер, запустите Docker Desktop и повторите команду."
    Start-Process "https://www.docker.com/products/docker-desktop/"
    Pause-Exit 1
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Desktop не запущен. Запустите его, дождитесь зелёного значка и повторите команду." -ForegroundColor Yellow
    Pause-Exit 1
}
Write-Host "[OK] Docker работает" -ForegroundColor Green

# 2. Настройки
$envFile = Join-Path $PSScriptRoot ".env"
$configured = $false
if (Test-Path $envFile) {
    $t = Get-Content $envFile -Raw
    if ($t -match "GATE_BOT_TOKEN=\d+:") { $configured = $true }
}
$redo = $true
if ($configured) {
    $a = Read-Host "Настройки уже есть. Заполнить заново? (y/N)"
    $redo = ($a -match '^[yYдД]')
}

if ($redo) {
    Write-Host ""
    Write-Host "Нужно 3 вещи: токен бота-привратника, ваш канал и ваш Telegram ID." -ForegroundColor Cyan
    Write-Host ""
    $token = (Read-Host "1/3 Токен бота-привратника (из @BotFather)").Trim()
    try { $me = Invoke-RestMethod ("https://api.telegram.org/bot" + $token + "/getMe") }
    catch { Write-Host "Токен не подошёл. Проверьте, что скопировали его целиком." -ForegroundColor Red; Pause-Exit 1 }
    $botUser = $me.result.username
    $botId = $me.result.id
    Write-Host ("[OK] Бот найден: @" + $botUser) -ForegroundColor Green

    $ch = (Read-Host "2/3 Ваш канал (например @mychannel)").Trim()
    if (-not $ch.StartsWith("@")) { $ch = "@" + $ch }
    try {
        $cm = Invoke-RestMethod ("https://api.telegram.org/bot" + $token + "/getChatMember?chat_id=" + $ch + "&user_id=" + $botId)
        if (@("administrator", "creator") -contains $cm.result.status) {
            Write-Host "[OK] Бот является администратором канала" -ForegroundColor Green
        } else {
            Write-Host "[!] Бот есть в канале, но НЕ администратор. Сделайте его админом, иначе проверка подписки не работает." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[!] Не удалось проверить канал. Добавьте бота @$botUser в АДМИНИСТРАТОРЫ канала $ch (иначе проверка подписки не работает)." -ForegroundColor Yellow
    }

    $admin = (Read-Host "3/3 Ваш Telegram ID (цифры, узнать: бот @userinfobot)").Trim()

    $lines = @(
        "GATE_BOT_TOKEN=$token",
        "GATE_BOT_USERNAME=$botUser",
        "CHANNEL=$ch",
        "CHANNEL_URL=https://t.me/" + $ch.TrimStart("@"),
        "ADMIN_IDS=$admin",
        "PANEL_URL=http://localhost:8000",
        "DEV_MODE=1",
        "COOKIE_SECURE=0",
        "MAX_BOTS_PER_USER=3",
        "BOT_MEM_MB=128",
        "BOT_CPU=0.25",
        "MAX_UPLOAD_MB=10"
    )
    [System.IO.File]::WriteAllText($envFile, ($lines -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "[OK] Настройки сохранены" -ForegroundColor Green
}

# 3. Запуск
Write-Host ""
Write-Host "Запускаю (первый раз может занять 3-5 минут)..." -ForegroundColor Cyan
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось запустить. Скопируйте ошибку выше и отправьте мне." -ForegroundColor Red
    Pause-Exit 1
}

Write-Host "Жду, пока сайт поднимется..."
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest "http://localhost:8000/api/config" -UseBasicParsing -TimeoutSec 2 | Out-Null; $ok = $true; break }
    catch { Start-Sleep -Seconds 2 }
}
if (-not $ok) {
    Write-Host "Сайт не ответил. Посмотрите логи: docker compose logs panel" -ForegroundColor Red
    Pause-Exit 1
}

Start-Process "http://localhost:8000"
Write-Host ""
Write-Host "=== ГОТОВО ===" -ForegroundColor Green
Write-Host "Сайт открыт: http://localhost:8000"
Write-Host "1) Введите свой Telegram ID и нажмите Войти (вы должны быть подписаны на канал)."
Write-Host "2) Добавить бота -> токен ВТОРОГО бота из @BotFather -> файл test-bot.zip (лежит в этой папке)."
Write-Host "3) Напишите @$botUser команду /start - появится меню."
Write-Host ""
Write-Host "Остановить: двойной клик по stop.bat"
Pause-Exit 0
