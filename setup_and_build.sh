#!/bin/bash
# CashControl — автоматическая сборка Linux-пакета
# Запуск: bash setup_and_build.sh

# Не останавливаемся на ошибках отдельных команд — каждая проверка автономна

echo "=== CashControl Linux Build ==="
echo ""

# ── 1. Проверка зависимостей ──────────────────────────────────────────

echo "[1/5] Проверка зависимостей..."

if ! command -v python3.12 &> /dev/null && ! command -v python3.11 &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "  ERROR: python3 не найден."
    echo "  Установите: sudo apt-get install python3 python3-venv"
    exit 1
fi

PYTHON_BIN=$(command -v python3.12 || command -v python3.11 || command -v python3)
echo "  Python: $PYTHON_BIN"

# Устанавливаем uv, если нет
if ! command -v uv &> /dev/null; then
    echo "  uv не найден — устанавливаю..."
    if command -v curl &> /dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget &> /dev/null; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "  WARNING: curl и wget не найдены. Установите uv вручную:"
        echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo "  Или: wget -qO- https://astral.sh/uv/install.sh | sh"
        echo "  Продолжаю без uv (будет использован pip)..."
    fi
    export PATH="$HOME/.local/bin:$PATH"
fi

# ── 2. Системные зависимости ──────────────────────────────────────────

echo ""
echo "[2/5] Системные зависимости..."

# Проверяем, есть ли уже нужные библиотеки
MISSING_SYS=""

if ! ldconfig -p 2>/dev/null | grep -q libsecret && ! find /usr/lib -name 'libsecret-1*' 2>/dev/null | grep -q .; then
    MISSING_SYS="$MISSING_SYS libsecret"
fi

if ! ldconfig -p 2>/dev/null | grep -q libpq && ! find /usr/lib -name 'libpq*' 2>/dev/null | grep -q .; then
    MISSING_SYS="$MISSING_SYS libpq"
fi

if [ -z "$MISSING_SYS" ]; then
    echo "  Все библиотеки уже установлены."
else
    echo "  Устанавливаю: $MISSING_SYS..."
    if command -v apt-get &> /dev/null; then
        # Пробуем установить — если репозитории не работают, продолжаем
        sudo apt-get update -qq 2>/dev/null || true
        sudo apt-get install -y -qq \
            libsecret-1-dev libpq-dev libxkbcommon-x11-0 \
            libxcb-xinerama0 libegl1 libopengl0 libxcb-cursor0 \
            2>/dev/null || {
            echo "  WARNING: apt не смог установить библиотеки."
            echo "  Попробуйте вручную:"
            echo "    sudo apt-get install libsecret-1-dev libpq-dev"
        }
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y libsecret-devel postgresql-devel 2>/dev/null || true
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm libsecret postgresql-libs 2>/dev/null || true
    elif command -v zypper &> /dev/null; then
        sudo zypper install -y libsecret-1-0 libpq5 2>/dev/null || true
    elif command -v apk &> /dev/null; then
        sudo apk add --no-cache libsecret libpq 2>/dev/null || true
    fi
fi

# ── 3. Виртуальное окружение ──────────────────────────────────────────

echo ""
echo "[3/5] Виртуальное окружение..."
$PYTHON_BIN -m venv .venv 2>/dev/null
source .venv/bin/activate
echo "  Venv создан: $(python --version)"

# ── 4. Python-зависимости ─────────────────────────────────────────────

echo ""
echo "[4/5] Python-зависимости..."

if command -v uv &> /dev/null; then
    uv pip install -e . 2>&1 || pip install -e .
else
    pip install -e .
fi

# ── 5. Сборка ─────────────────────────────────────────────────────────

echo ""
echo "[5/5] Сборка..."
python scripts/build_linux.py

echo ""
echo "=== Готово ==="
echo ""
echo "Пакет: dist/CashControl-linux-x86_64.tar.gz"
echo "Или распакованная папка: dist/CashControl/"
echo ""
echo "Запуск:"
echo "  cd dist/CashControl && ./run.sh"
echo ""
echo "Установка в систему:"
echo "  sudo cp CashControl.desktop /usr/share/applications/"
echo "  sudo cp icon.png /usr/share/icons/hicolor/128x128/apps/"
