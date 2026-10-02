"""Regenerate csi_hengyu_s84e.json from S84E_ID_map.txt (firmware key map)
and the POS XML keyboard config (button labels)."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

KB_LAYOUTS_DIR = Path(r"D:\Project\CashControl_3\src\cashcontrol\gui\widgets\keyboard_layouts")
ID_MAP_PATH = Path(r"D:\Project\CashControl_3\S84E_ID_map.txt")
XML_PATH = Path(r"D:\Project\CashControl_3\dist\keyboard-csi_hengyu_s84e-0-kbd.xml")

COLS = 12
ROWS = 7

# Column positions map (from old XML generator)
ROW_COLS: list[int] = [0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12]
# Actual button IDs per physical position (A01..G12) → column index


def parse_id_map(text: str) -> dict[str, tuple[str, str]]:
    """Parse S84E_ID_map.txt into {button_id: (code_hex, key_char_or_combo)}."""
    result: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        # Skip header/comment/blank lines
        if not line or line.startswith("#") or line.startswith("S84E") or line.startswith("ID"):
            continue
        if line.startswith("-"):
            continue
        
        parts = line.split()
        if len(parts) < 3:
            continue
        
        button_id = parts[0]  # e.g. "A01"
        code = parts[1]       # e.g. "44"
        b5 = parts[2]         # e.g. "6"
        b7 = parts[3]         # e.g. "01"
        combo_desc = " ".join(parts[4:])  # e.g. "F6" or "<Left Shift Down><1><Left Shift Up> (ПОДТВЕРЖДЕНО)"
        
        # Extract key/combo from description (strip trailing markers/comments)
        # Description format: key or "<mod><key><mod>"
        clean = re.sub(r"\s*\(\*\)\s*$", "", combo_desc)
        clean = re.sub(r"\s*\(ПОДТВЕРЖДЕНО\)\s*$", "", clean)
        clean = clean.strip()
        
        result[button_id] = (code, clean)
    return result


def parse_button_list() -> list[str]:
    """Generate button IDs in physical order A01..G12."""
    result = []
    for row in "ABCDEFG":
        for col in range(1, 13):
            result.append(f"{row}{col:02d}")
    return result


def clean_combo(s: str) -> str:
    """Convert <Left Shift Down><1><Left Shift Up> to Shift+1."""
    s = s.strip()
    if not s:
        return ""
    # Single word key like "F6", "Enter", "0", "q"
    if "<" not in s:
        return s
    # Combo like <Left Shift Down><key><Left Shift Up>
    m = re.search(r"<Left Shift Down><([^>]+)><Left Shift Up>", s)
    if m:
        key = m.group(1).strip()
        # Convert to internal action format expected by build_xdotool_cmd
        return f"Shift+{key}"
    return s


def parse_xml_labels(path: Path) -> dict[tuple[int, int], str]:
    """Parse POS XML keyboard config into {(row, col): label}.
    XML coords: column = (X-55)//54, row = (Y-131)//54."""
    root = ET.parse(path).getroot()
    result: dict[tuple[int, int], str] = {}
    for elem in root:
        scan_elem = elem.find("ScanCode")
        ch_elem = elem.find("Ch")
        if scan_elem is None or ch_elem is None:
            continue
        x = int(scan_elem.get("X", "0"))
        y = int(scan_elem.get("Y", "0"))
        col = (x - 55) // 54
        row = (y - 131) // 54
        if 0 <= row < ROWS and 0 <= col < COLS:
            result[(row, col)] = ch_elem.text.strip() if ch_elem.text else ""
    return result


def main():
    text = ID_MAP_PATH.read_text(encoding="utf-8")
    id_map = parse_id_map(text)
    xml_labels = parse_xml_labels(XML_PATH)
    
    # Build full 7×13 grid with empty cells
    grid = [[None] * COLS for _ in range(ROWS)]
    
    # Physical position → grid: button A01..A12 → row 0..6, col 0..11 (1:1)
    btn_col_to_grid = {i: i - 1 for i in range(1, 13)}
    
    for row_idx, row_letter in enumerate("ABCDEFG"):
        for btn_col in range(1, 13):
            btn_id = f"{row_letter}{btn_col:02d}"
            entry = id_map.get(btn_id)
            if entry is None:
                continue
            code, combo = entry
            grid_col = btn_col_to_grid[btn_col]
            
# Convert combo to internal action format
            action = clean_combo(combo)

            # Prefer the POS label from XML, else leave the button unlabeled
            # (the key action is still attached)
            button_text = xml_labels.get((row_idx, grid_col), "")
            
            grid[row_idx][grid_col] = {
                "name": f"btn_{row_idx * COLS + grid_col}",
                "text": button_text,
                "action": action,
            }
    
    # Flatten into list
    layout: list[dict] = []
    for row in grid:
        for cell in row:
            if cell:
                layout.append(cell)
            else:
                idx = len(layout)
                layout.append({"name": f"btn_{idx}", "text": "", "action": ""})
    
    out_path = KB_LAYOUTS_DIR / "csi_hengyu_s84e.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)
    
    print(f"Generated {out_path}")
    count = sum(1 for b in layout if b["action"])
    print(f"Total: {len(layout)}, Active: {count}")
    
    # Print grid for verification
    for r in range(ROWS):
        row_str = []
        for c in range(COLS):
            btn = grid[r][c]
            label = btn["text"] if btn and btn["text"] else "."
            row_str.append(f"{label:>6}")
        print("  " + " | ".join(row_str))


if __name__ == "__main__":
    main()