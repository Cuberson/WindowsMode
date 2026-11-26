@echo off
setlocal
rem Builds Conductor.exe with PyInstaller (onefile, no console window).
rem Run from anywhere: double-click this file, or  .\scripts\build-exe.bat

cd /d "%~dp0.."
echo === Conductor build ===

rem Prefer an active venv / plain python; fall back to the py launcher.
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    echo Python 3.11+ was not found on PATH. Install it from https://python.org
    goto :fail
)

%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :fail

%PY% -m pip install "pyinstaller>=6.0"
if errorlevel 1 goto :fail

%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name Conductor --collect-all keyring --hidden-import keyring.backends.Windows --hidden-import winsdk.windows.media.speechrecognition run.pyw
if errorlevel 1 goto :fail

echo.
echo Built: dist\Conductor.exe
echo Copy it anywhere (e.g. %%LOCALAPPDATA%%\Programs\Conductor\) and run it.
echo The tray icon appears in the notification area; hold Ctrl+Shift+Space and talk.
goto :end

:fail
echo.
echo Build FAILED (exit code %errorlevel%).
set "EXITCODE=%errorlevel%"
if "%EXITCODE%"=="0" set "EXITCODE=1"

:end
rem Keep the window open when launched by double-click.
echo %cmdcmdline% | find /i "/c" >nul && pause
if defined EXITCODE exit /b %EXITCODE%
exit /b 0
