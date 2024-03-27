@echo off
echo Starting virtual environment...
call .\venv\Scripts\activate

echo Starting Flask application...
python app.py

pause
