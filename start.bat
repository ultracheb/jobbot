@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python не знойдзены. Усталюй з https://www.python.org/downloads/ ^(пастаў галку "Add python.exe to PATH"^) і запусці зноў.
  pause
  exit /b 1
)

if not exist .venv (
  echo Раблю віртуальнае асяроддзе...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

if not exist .env (
  copy .env.example .env >nul
  echo.
  echo Адкрыю .env. Устаў токен ад @BotFather пасля TELEGRAM_TOKEN=, захавай і зачыні.
  notepad .env
)

echo Запускаю бота. Не закрывай гэтае акно.
python bot.py
pause
