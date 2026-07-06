@echo off
chcp 65001 > nul
echo Установка зависимостей...
python -m pip install -r requirements.txt
if errorlevel 1 pause && exit /b 1
echo Запуск игры...
python main.py
pause
