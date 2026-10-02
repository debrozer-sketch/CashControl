"""Generate JSON layout for hengyu_s78d keyboard from XML."""
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
import json

KB_LAYOUTS_DIR = Path(r"D:\Project\CashControl_3\src\cashcontrol\gui\widgets\keyboard_layouts")
XML_FILES = [
    r"D:\Project\CashControl_3\dist\keyboard-hengyu_s78d-0-kbd.xml",
    r"D:\Project\CashControl_3\dist\keyboard-hengyu_s78d-1-kbd.xml",
    r"D:\Project\CashControl_3\dist\keyboard-hengyu_s78d-2-kbd.xml",
    r"D:\Project\CashControl_3\dist\keyboard-hengyu_s78d-3-kbd.xml",
    r"D:\Project\CashControl_3\dist\keyboard-hengyu_s78d-4-kbd.xml",
    r"D:\Project\CashControl_3\dist\keyboard-hengyu_s78d-5-kbd.xml",
]

# Map function key commands to F-codes
CMD_KEYSYM = {
    "kbdUp": "Up",
    "kbdDown": "Down",
    "kbdLeft": "Left",
    "kbdRight": "Right",
    "kbdEnter": "Return",
    "kbdCancel": "Escape",
    "kbdCheck": "F11",
    "kbdDocLastCopy": "F8",
    "kbdBox": "Ctrl+q",
    "kbdExit": "F12",
    "kbdPositionDiscounts": "F6",
    "kbdLogin": "F3",
    "kbdMenu": "F10",
    "kbdSum": "F7",
    "kbdSearch": "F9",
    "kbdPay": "F5",
    "kbdBarcode": "F1",
}

def parse_xml(xml_path):
    """Parse XML file and return grid of buttons."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    count_x = int(root.get("CountX", 7))
    count_y = int(root.get("CountY", 8))
    
    grid = {}
    
    for elem in root:
        tag = elem.tag
        if tag == "ScanCode":
            continue
        
        scan_elem = elem.find("ScanCode")
        ch_elem = elem.find("Ch")
        cmd_elem = elem.find("Command")
        
        if scan_elem is None or ch_elem is None:
            continue
        
        x = int(scan_elem.get("X", 0))
        y = int(scan_elem.get("Y", 0))
        code = int(scan_elem.text.strip())
        ch = ch_elem.text.strip() if ch_elem is not None else ""
        cmd = cmd_elem.text.strip() if cmd_elem is not None and cmd_elem.text else None
        
        # Determine row and col from x,y
        # For 13x6 grid: x in [271, 379, 433, 487, 541, 595, 649, 703]
        # For 7x8 grid: x in [217, 271, 325, 379, 433, 487, 541]
        
        # Find closest grid position
        row = None
        col = None
        
        # Known y positions for 6-row layout
        y_positions_6 = [131, 185, 239, 293, 347, 401]
        x_positions_6 = [271, 379, 433, 487, 541, 595, 649, 703]
        
        for ri, yp in enumerate(y_positions_6):
            if abs(y - yp) < 30:
                row = ri
                break
        
        if row is None:
            continue
        
        # Find col
        if count_x == 13:
            # 13 columns: some positions have multiple buttons
            # Simplification: map based on x
            if x in x_positions_6:
                base_col = x_positions_6.index(x)
                col = base_col
            elif x < 271:
                col = 0
            else:
                col = len(x_positions_6)
        else:
            for ci, xp in enumerate(x_positions_6[:count_x]):
                if abs(x - xp) < 30:
                    col = ci
                    break
        
        if col is None or row is None:
            continue
        
        # Determine action
        action = ch
        if cmd and cmd in CMD_KEYSYM:
            action = CMD_KEYSYM[cmd]
        
        grid[(row, col)] = {
            "action": action,
            "text": ch,
        }
    
    return grid, count_x, count_y

def main():
    combined = {}
    max_cols = 0
    max_rows = 0
    
    for xml_path in XML_FILES:
        p = Path(xml_path)
        if not p.exists():
            print(f"Skipping missing: {xml_path}", file=sys.stderr)
            continue
        
        grid, count_x, count_y = parse_xml(str(p))
        max_cols = max(max_cols, count_x)
        max_rows = max(max_rows, count_y)
        combined.update(grid)
    
    # Convert to list format
    layout = []
    for row in range(max_rows):
        for col in range(max_cols):
            if (row, col) in combined:
                layout.append(combined[(row, col)])
            else:
                layout.append(None)
    
    result = {
        "name": "Hengyu S78D (6×13)",
        "layout": layout,
        "cols": max_cols,
    }
    
    out_path = KB_LAYOUTS_DIR / "hengyu_s78d.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"Generated {out_path}: {max_rows}x{max_cols} grid, {len(combined)} buttons")

if __name__ == "__main__":
    main()
