@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================
echo   Servis Rota Optimizasyonu
echo   Esnek Rota Dolulugu Surumu
echo ==============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    set "PY=python"
)

%PY% --version >nul 2>nul
if errorlevel 1 (
    echo Python bulunamadi. Once Python 3.11 veya 3.12 kurun.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Ilk kurulum yapiliyor...
    %PY% -m venv .venv
    if errorlevel 1 goto :error
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 goto :error
) else (
    call ".venv\Scripts\activate.bat"
)

echo.
echo Sistem aciliyor...
python -m streamlit run app.py
goto :eof

:error
echo.
echo Kurulum sirasinda bir hata olustu.
pause
exit /b 1
