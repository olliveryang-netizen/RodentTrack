@echo off
chcp 65001 >nul
REM RodentTrack launcher for Windows: double-click this file.
REM First run: creates a private Python environment (.venv) and installs the packages (needs internet, 1-3 min).
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo [RodentTrack] Python 3 was not found.  未找到 Python 3。
  echo Install Python 3.9 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during installation, then double-click this file again.
  echo 请从 https://www.python.org/downloads/ 安装 Python 3.9 以上版本，安装时勾选 "Add python.exe to PATH"，然后重新双击本文件。
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [RodentTrack] First start: creating .venv ...  首次启动：正在创建运行环境...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment.  无法创建运行环境。
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import cv2, numpy, pandas, matplotlib" >nul 2>nul
if errorlevel 1 (
  echo [RodentTrack] Installing packages, please wait ...  正在安装组件，请稍候...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Installation failed. Check the internet connection and try again.  安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)

start "" ".venv\Scripts\pythonw.exe" mouse_tracker_gui.py
exit /b 0
