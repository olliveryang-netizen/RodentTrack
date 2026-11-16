#!/bin/bash
# Shared launcher for macOS and Linux. Creates .venv on first run and installs the packages.
cd "$(dirname "$0")/.." || exit 1

find_python() {
  for p in python3.13 python3.12 python3.11 python3.10 python3.9 python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
      echo "$p"; return 0
    fi
  done
  return 1
}

if [ ! -x ".venv/bin/python" ]; then
  PY=$(find_python)
  if [ -z "$PY" ]; then
    echo ""
    echo "[RodentTrack] No Python 3.9+ with tkinter was found.  未找到带 tkinter 的 Python 3.9 以上版本。"
    if [ "$(uname)" = "Darwin" ]; then
      echo "  macOS: install Python from https://www.python.org/downloads/macos/ (includes tkinter),"
      echo "         or with Homebrew:  brew install python-tk"
      echo "  请从 python.org 下载安装 macOS 版 Python（自带 tkinter），或用 Homebrew: brew install python-tk"
    else
      echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-tk"
      echo "  Fedora:        sudo dnf install python3 python3-tkinter"
    fi
    echo ""
    read -r -p "Press Enter to close / 按回车关闭 " _
    exit 1
  fi
  echo "[RodentTrack] First start: creating .venv with $PY ...  首次启动：正在创建运行环境..."
  "$PY" -m venv .venv || { echo "venv failed (Ubuntu: sudo apt install python3-venv)"; read -r _; exit 1; }
fi

if ! .venv/bin/python -c "import cv2, numpy, pandas, matplotlib" >/dev/null 2>&1; then
  echo "[RodentTrack] Installing packages, please wait ...  正在安装组件，请稍候..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt || { echo "Installation failed / 安装失败"; read -r _; exit 1; }
fi

exec .venv/bin/python mouse_tracker_gui.py
