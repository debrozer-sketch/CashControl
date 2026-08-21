import sys
sys.path.insert(0, r"D:\Project\cashcontrol3\src")
from cashcontrol.core.info.info_manager import CashInfoSnapshot, InfoSection, CollectionStatus
from cashcontrol.core.info.rules import ProblemChecker

pc = ProblemChecker()
dc_section = "Денежный ящик"

cases = [
    ("true", "pos", 1),
    ("false", "pos", 0),
    ("t", "pos", 1),
    ("f", "pos", 0),
    ("true", "touch", 1),
    ("true", "sco3", 0),
    (None, "pos", 1),
]
for raw, ct, expected in cases:
    snap = CashInfoSnapshot(host="test")
    snap.drawer_close = InfoSection("drawer_close", CollectionStatus.OK, data={"drawer_close_raw": raw})
    issues = pc.check(snap, ct)
    dc_issues = [i for i in issues if i.section == dc_section]
    ok = len(dc_issues) == expected
    print(f"raw={raw!r}, ct={ct}: {len(dc_issues)} issues (expected {expected}) {'OK' if ok else 'FAIL'}")
