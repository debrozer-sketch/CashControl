import sys
sys.path.insert(0, r"D:\Project\cashcontrol3\src")
import json
from cashcontrol.core.info.info_manager import CashInfoSnapshot, InfoSection, CollectionStatus, ALL_SECTIONS
from cashcontrol.core.info.rules import ProblemChecker

print("ALL_SECTIONS has payment_ranks:", "payment_ranks" in ALL_SECTIONS)
snap = CashInfoSnapshot(host="test")
print("payment_ranks attr exists:", hasattr(snap, "payment_ranks"))
print("Initial status:", snap.payment_ranks.status)

pc = ProblemChecker()

# Test 1: mismatched ranks
snap.payment_ranks = InfoSection("payment_ranks", CollectionStatus.OK, data={
    "payment_ranks_raw": '{"paymentTypesRanks":[],"paymentTypesWithCounterpartyRanks":[]}',
})
issues = pc.check(snap, "sco3")
print("Issues for bad ranks (sco3):", [(i.section, i.message) for i in issues])

# Test 2: correct ranks
expected = json.dumps({
    "paymentTypesRanks": [
        {"paymentId": "BankCardPaymentEntity", "bankId": "Сбербанк", "fastAccessRank": 1, "rank": 1},
        {"paymentId": "BankQRPaymentEntity", "bankId": "ГазпромБанк СБП", "fastAccessRank": 2, "rank": 2},
    ],
    "paymentTypesWithCounterpartyRanks": [
        {"paymentId": "BankCardPaymentEntity", "bankId": "Сбербанк", "fastAccessRank": 1, "rank": 1},
        {"paymentId": "BankQRPaymentEntity", "bankId": "ГазпромБанк СБП", "fastAccessRank": 2, "rank": 2},
    ],
})
snap2 = CashInfoSnapshot(host="test")
snap2.payment_ranks = InfoSection("payment_ranks", CollectionStatus.OK, data={"payment_ranks_raw": expected})
issues2 = pc.check(snap2, "sco3")
print("Issues for correct ranks (sco3):", len(issues2), "(should be 0)")

# Test 3: not sco3
issues3 = pc.check(snap2, "pos")
print("Issues for pos:", len(issues3), "(should be 0, only EnableUSB rule fires)")

# Test 4: None raw value
snap3 = CashInfoSnapshot(host="test")
snap3.payment_ranks = InfoSection("payment_ranks", CollectionStatus.OK, data={"payment_ranks_raw": None})
issues4 = pc.check(snap3, "sco3")
print("Issues for None raw:", [(i.section, i.message) for i in issues4])

print("\nAll tests passed!")
