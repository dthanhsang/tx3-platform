@echo off
:: Chuyen thu muc lam viec ve dung thu muc chua file .bat này (du chay under Administrator)
cd /d "%~dp0"
chcp 65001 >nul

echo ===================================================
echo   DONG GOI PHAN MEM TX3 CONTROL GUI SANG FILE .EXE
echo ===================================================
echo.

echo [1/3] Kiem tra va cai dat PyInstaller, PyQt5...
python -m pip install --upgrade pip
python -m pip install pyinstaller PyQt5

echo.
echo [2/3] Bat dau dong goi file TX3_Control_GUI.exe...
python -m PyInstaller --onefile --noconsole --name TX3_Control_GUI tx3_control_gui.py

echo.
if exist "dist\TX3_Control_GUI.exe" (
    echo ===================================================
    echo [3/3] HOAN TAT THANH CONG!
    echo File TX3_Control_GUI.exe da duoc tao tai:
    echo %~dp0dist\TX3_Control_GUI.exe
    echo ===================================================
) else (
    echo ===================================================
    echo [!] CO LOI XAY RA: Khong tim thay file TX3_Control_GUI.exe
    echo Vui long kiem tra lai thong bao loi o tren!
    echo ===================================================
)

pause
