"""Generate hengyu_s78a.json from S78A_ID_map.txt (firmware keymap).
Maps firmware ASCII keys to POS-style Russian labels."""
import json
import re
from pathlib import Path

KB_LAYOUTS_DIR = Path(r"D:\Project\CashControl_3\src\cashcontrol\gui\widgets\keyboard_layouts")
ID_MAP_PATH = Path(r"D:\Project\CashControl_3\S78A_ID_map.txt")
OUT_STEM = "hengyu_s78a"

COLS = 13
ROWS = 6

_ACTION_ALIASES = {
    "Page Up": "PageUp",
    "Page Down": "PageDown",
    "Scroll Lock": "ScrollLock",
    "Caps Lock": "CapsLock",
}

# Firmware ASCII name → POS-style Russian visual label
_LABEL_MAP = {
    # Row A
    "Insert":   "Сброс",
    "F1":       "Формат",
    "F2":       "Регистр",
    "F5":       "Поиск",
    "F6":       "РедактЧек",
    "F7":       "Печать",
    "F9":       "Копия",
    "F10":      "Ящик",
    "F11":      "Выход",
    "F12":      "Ввод",
    # Row B
    "Q":        "Мясо",
    "W":        "Хлеб",
    "E":        "Молоко",
    "Y":        "Овощи",
    "U":        "Фрукты",
    "I":        "Сладкое",
    "O":        "Пакеты",
    "P":        "Карта",
    "[":        "Скидки",
    "]":        "Лояльность",
    # Row C
    "A":        "Рыба",
    "S":        "Заморозка",
    "D":        "Выпечка",
    "7":        "7",
    "8":        "8",
    "9":        "9",
    "J":        "Контейнер",
    "K":        "Вес",
    "L":        "Валюта",
    ";":        "Итог",
    # Row D
    "Z":        "Цитрусы",
    "X":        "Сезонные",
    "C":        "Конфеты",
    "4":        "4",
    "5":        "5",
    "6":        "6",
    "M":        "Сбер",
    ".":        ",",
    "/":        "QR",
    "Space":    "Пробел",
    # Row E
    "\\":       "Вверх",
    "`":        "Ввод",
    "N":        "Телефон",
    "1":        "1",
    "2":        "2",
    "3":        "3",
    "Home":     "Домой",
    "Page Up":  "Стр.вверх",
    "F4":       "Сброс",
    "T":        "Все ГК",
    # Row F
    "G":        "ГК 1",
    "B":        "ГК 2",
    "H":        "ГК 3",
    "0":        "0",
    "-":        "00",
    ",":        ",",
    "End":      "Конец",
    "Page Down":"Стр.вниз",
    "Scroll Lock": "Scroll",
    "Enter":    "Ввод",
}


def _to_action(name: str) -> str:
    name = name.strip()
    if not name:
        return ""
    if name in _ACTION_ALIASES:
        return _ACTION_ALIASES[name]
    return name


def _visual_label(action: str) -> str:
    return _LABEL_MAP.get(action, action)


def parse_id_map(text: str) -> dict[str, tuple[str, str]]:
    """Parse S78A_ID_map.txt into {button_id: (action_name, visual_label)}."""
    result: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "<empty>" in line:
            continue
        fields = line.split("`t")
        if len(fields) < 6:
            continue
        button_id = fields[0]
        raw = fields[-1].strip()
        raw = re.sub(r"\s*\(.*\)\s*$", "", raw).strip()
        action = _to_action(raw)
        result[button_id] = (action, _visual_label(action))
    return result


def main() -> None:
    text = ID_MAP_PATH.read_text(encoding="utf-8")
    id_map = parse_id_map(text)

    grid = [[None] * COLS for _ in range(ROWS)]

    for row_idx, row_letter in enumerate("ABCDEF"):
        for btn_col in range(1, 14):
            btn_id = f"{row_letter}{btn_col:02d}"
            entry = id_map.get(btn_id)
            if entry is None:
                continue
            action, visual = entry
            grid_col = btn_col - 1
            grid[row_idx][grid_col] = {
                "name": f"btn_{row_idx * COLS + grid_col}",
                "text": visual,
                "action": action,
            }

    layout: list[dict] = []
    for row in grid:
        for cell in row:
            cell = cell or {"text": "", "action": ""}
            cell.setdefault("name", f"btn_{len(layout)}")
            layout.append(cell)

    out_path = KB_LAYOUTS_DIR / f"{OUT_STEM}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)

    print(f"Generated {out_path}")
    count = sum(1 for b in layout if b["action"])
    texts = sum(1 for b in layout if b["text"])
    print(f"Total: {len(layout)}, Active actions: {count}, With text: {texts}")

    for r in range(ROWS):
        row_str = []
        for c in range(COLS):
            btn = grid[r][c]
            if btn and btn["text"]:
                row_str.append(f"{btn['text'][:8]}")
            else:
                row_str.append(".          ")
        print("  " + " | ".join(row_str))


if __name__ == "__main__":
    main()
