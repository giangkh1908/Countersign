"""Dữ liệu analytics nhỏ (CRM/bán hàng giả lập): 40 khách hàng, 12 sản phẩm, 300 đơn."""

from __future__ import annotations

import random
from datetime import date, timedelta

from .users import User

N_CUSTOMERS, N_ORDERS = 40, 300
SEGMENTS = {"Enterprise": 4, "SMB": 16, "Retail": 20}
STATUS_COUNTS = {"completed": 246, "cancelled": 24, "refunded": 15, "pending": 15}
REGIONS = ["Bắc"] * 14 + ["Trung"] * 6 + ["Nam"] * 20
LAST_DATE = date(2026, 9, 30)
SEASON = {
    1: 0.95,
    2: 0.70,
    3: 0.95,
    4: 1.0,
    5: 1.0,
    6: 1.05,
    7: 0.95,
    8: 0.95,
    9: 1.05,
    10: 1.1,
    11: 1.35,
    12: 1.45,
}
PRODUCTS = [
    ("PRD-CB-01", "Gói Cơ bản 10 người dùng", "Phần mềm", 1_500_000),
    ("PRD-CB-02", "Gói Cơ bản 25 người dùng", "Phần mềm", 3_200_000),
    ("PRD-NC-01", "Gói Nâng cao 50 người dùng", "Phần mềm", 9_500_000),
    ("PRD-NC-02", "Gói Nâng cao 200 người dùng", "Phần mềm", 32_000_000),
    ("PRD-DV-01", "Triển khai và cấu hình", "Dịch vụ", 12_000_000),
    ("PRD-DV-02", "Đào tạo người dùng cuối", "Dịch vụ", 4_500_000),
    ("PRD-DV-03", "Tư vấn quy trình", "Dịch vụ", 18_000_000),
    ("PRD-HT-01", "Hỗ trợ tiêu chuẩn (năm)", "Hỗ trợ", 6_000_000),
    ("PRD-HT-02", "Hỗ trợ ưu tiên 24/7 (năm)", "Hỗ trợ", 45_000_000),
    ("PRD-TH-01", "Tích hợp kế toán", "Tích hợp", 15_000_000),
    ("PRD-TH-02", "Tích hợp thương mại điện tử", "Tích hợp", 22_000_000),
    ("PRD-TH-03", "Tích hợp tuỳ chỉnh", "Tích hợp", 120_000_000),
]
HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi"]
TEN = ["Anh", "Bảo", "Cường", "Dung", "Giang", "Hải", "Khoa", "Linh", "Minh", "Nga"]
CO = [
    "Phát Đạt",
    "Hưng Thịnh",
    "Đại Việt",
    "Thành Công",
    "An Khang",
    "Minh Long",
    "Sao Mai",
    "Bình An",
]


def build_analytics(users: list[User], seed: int) -> dict[str, list[dict]]:
    rng = random.Random(f"{seed}:analytics")
    reps = [u for u in users if u.department == "SALES" and "employee" in u.roles]
    segs = [s for s, n in SEGMENTS.items() for _ in range(n)]
    rng.shuffle(segs)
    customers = []
    for i in range(1, N_CUSTOMERS + 1):
        seg = segs[i - 1]
        name = (
            f"Công ty TNHH {rng.choice(CO)} {i}"
            if seg != "Retail"
            else f"{rng.choice(HO)} {rng.choice(TEN)}"
        )
        customers.append(
            {
                "id": i,
                "name": name,
                "segment": seg,
                "region": REGIONS[(i * 7) % len(REGIONS)],
                "phone": f"09{rng.randint(10_000_000, 99_999_999)}",
                "email": f"khach{i:03d}@example.com",
                "tax_code": f"{rng.randint(10**9, 10**10 - 1)}",
                "account_manager_sub": rng.choice(reps).sub,
                "owning_dept": "CS" if i % 10 == 0 else "SALES",  # 10% thuộc CS
            }
        )
    products = [
        {"id": i, "sku": s, "name": n, "category": c, "price_vnd": p}
        for i, (s, n, c, p) in enumerate(PRODUCTS, 1)
    ]
    # ngày đơn theo mùa vụ: trọng số theo tháng, 24 tuần-ngày gần nhất 12 tháng
    days = [LAST_DATE - timedelta(days=d) for d in range(365)]
    weights = [SEASON[d.month] * (0.3 if d.weekday() == 6 else 1.0) for d in days]
    statuses = [s for s, n in STATUS_COUNTS.items() for _ in range(n)]
    rng.shuffle(statuses)
    anomalies = set(rng.sample(range(1, N_ORDERS + 1), 3))  # 3 đơn bất thường (x20)
    orders, items = [], []
    for oid in range(1, N_ORDERS + 1):
        cust = rng.choice(customers)
        n_lines = rng.randint(1, 4)
        total = 0
        for prod in rng.sample(products, n_lines):
            qty = (
                rng.choice([1, 1, 2, 3, 5])
                if cust["segment"] != "Enterprise"
                else rng.randint(2, 10)
            )
            if oid in anomalies:
                qty *= 20
            items.append(
                {
                    "id": len(items) + 1,
                    "order_id": oid,
                    "product_id": prod["id"],
                    "quantity": qty,
                    "unit_price_vnd": prod["price_vnd"],
                }
            )
            total += qty * prod["price_vnd"]
        orders.append(
            {
                "id": oid,
                "customer_id": cust["id"],
                "order_date": rng.choices(days, weights)[0],
                "status": statuses[oid - 1],
                "total_vnd": total,
                "sales_rep_sub": rng.choice(reps).sub,
                "owning_dept": cust["owning_dept"],
            }
        )
    return {"customers": customers, "products": products, "orders": orders, "order_items": items}
