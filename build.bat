@echo off
REM Windows에서 단일 실행 파일(.exe)을 만듭니다.
REM 준비물: Python 3.11 이상
setlocal

if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --clean ^
  --name "TodoTBD" ^
  --windowed ^
  --onefile ^
  main.py

echo.
echo 완성: dist\TodoTBD.exe
endlocal
