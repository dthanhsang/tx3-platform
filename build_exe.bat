@echo off
cd /d "%~dp0"
chcp 65001 >nul

echo ===================================================
echo   DONG GOI PHAN MEM TX3 CONTROL GUI SANG FILE .EXE
echo ===================================================
echo.

echo [1/3] Kiem tra & Tu dong cai dat thu vien Python con thieu...
echo Dang kiem tra cac thu vien: PyInstaller, PyQt5, Pillow, requests...
python -c "import PyInstaller, PyQt5, PIL, requests" 2>nul
if %errorlevel% neq 0 (
    echo [!] Phat hien thieu thu vien Python. Dang cai dat...
    python -m pip install --upgrade pip
    python -m pip install pyinstaller PyQt5 Pillow requests
    echo [OK] Hoan tat cai dat cac thu vien Python!
) else (
    echo [OK] Tat ca thu vien Python da co san.
)

echo.
echo [2/3] Bat dau dong goi file TX3_Control_GUI.exe...
if exist "dist\TX3_Control_GUI.exe" del /f /q "dist\TX3_Control_GUI.exe"

python -m PyInstaller --clean --onefile --noconsole --name TX3_Control_GUI --add-data "rom-builder;rom-builder" --add-data "rombuilder;rombuilder" --add-data "tools;tools" tx3_control_gui.py

echo.
if exist "dist\TX3_Control_GUI.exe" (
    echo ===================================================
    echo [3/3] HOAN TAT THANH CONG!
    echo File TX3_Control_GUI.exe da duoc tao tai:
    echo %~dp0dist\TX3_Control_GUI.exe
    echo ===================================================
) else (
    echo ===================================================
    echo [!] CO LOI XAY RA TRONG QUA TRINH PYINSTALLER BUILD:
    echo Kiem tra lai thong bao loi mau do/vang phia tren!
    echo ===================================================
)

pause
