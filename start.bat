@echo off
echo ==========================================
echo    Установка и запуск TG-Parser...
echo ==========================================
echo.

if not exist ".venv" (
    echo [1/3] Создаю виртуальное окружение...
    python -m venv .venv
)

echo [2/3] Активация окружения и установка зависимостей...
call .venv\Scripts\activate
pip install -r requirements.txt

echo [3/3] Запускаю приложение... 
echo.
echo Откройте в браузере: http://localhost:8000
echo.
uvicorn main:app --host 0.0.0.0 --port 8000
pause
