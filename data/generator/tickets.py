"""100 ticket cho 2 phòng xử lý (SALES, HR); mọi sub tham chiếu là user trong realm."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from .users import User, staff_of

REFERENCE_NOW = datetime(2026, 10, 1, tzinfo=UTC)  # mốc cố định, không dùng đồng hồ máy
N_TICKETS = 100
DEPT_COUNTS = {"SALES": 55, "HR": 45}
STATUS_COUNTS = {"open": 20, "in_progress": 25, "resolved": 25, "closed": 30}
PRIORITY_COUNTS = {"low": 25, "medium": 45, "high": 22, "urgent": 8}

CATEGORIES = {
    "SALES": ["quote_support", "refund_request", "complaint", "feature_request"],
    "HR": ["leave_request", "payroll_query", "account_access", "other"],
}
TITLES = {
    "quote_support": [
        "Cần hỗ trợ lập báo giá gói Nâng cao",
        "Xác nhận chiết khấu cho đơn hàng lớn",
    ],
    "refund_request": [
        "Khách hàng yêu cầu hoàn tiền đơn hàng",
        "Hoàn tiền do huỷ dịch vụ trong 7 ngày",
    ],
    "complaint": ["Khách hàng phản ánh chậm phản hồi", "Khiếu nại về chất lượng hỗ trợ"],
    "feature_request": [
        "Đề xuất bổ sung báo cáo doanh số theo vùng",
        "Yêu cầu thêm trường tuỳ chỉnh trong CRM",
    ],
    "leave_request": ["Đề nghị xác nhận số ngày phép còn lại", "Đăng ký nghỉ phép dài ngày"],
    "payroll_query": [
        "Thắc mắc về khoản khấu trừ trên phiếu lương",
        "Hỏi về thời điểm chi trả thưởng",
    ],
    "account_access": ["Không đăng nhập được cổng nhân sự", "Cấp quyền xem hồ sơ cá nhân"],
    "other": ["Xin giấy xác nhận công tác", "Cập nhật thông tin liên hệ khẩn cấp"],
}
DETAIL = [
    "Vấn đề phát sinh từ đầu tuần này và ảnh hưởng đến công việc hằng ngày.",
    "Đã thử các cách xử lý thông thường nhưng chưa có kết quả.",
    "Mong được phản hồi sớm để kịp tiến độ chung của nhóm.",
    "Đính kèm thông tin chi tiết trong phần bình luận bên dưới.",
]
COMMENTS = [
    "Đã tiếp nhận, đang kiểm tra thông tin.",
    "Vui lòng bổ sung thêm chi tiết để xử lý nhanh hơn.",
    "Đã chuyển cho bộ phận liên quan xem xét.",
    "Đã xử lý xong, nhờ bạn xác nhận lại.",
]
INTERNAL = [
    "Ghi chú nội bộ: cần đối chiếu với hồ sơ gốc trước khi phản hồi.",
    "Ghi chú nội bộ: trường hợp này đã từng xảy ra, xem ticket cũ.",
]
RESOLUTION = [
    "Đã xử lý theo quy trình và xác nhận với người yêu cầu.",
    "Đã cấp quyền/điều chỉnh theo đề nghị.",
    "Đã giải thích chính sách và đóng yêu cầu.",
]
PERSON = ["Nguyễn Thị Mai", "Trần Văn Hùng", "Lê Quốc Bảo", "Phạm Thu Hà", "Võ Minh Tuấn"]


def _quota(rng: random.Random, counts: dict[str, int]) -> list[str]:
    items = [k for k, n in counts.items() for _ in range(n)]
    rng.shuffle(items)
    return items


def build_tickets(users: list[User], seed: int) -> dict[str, list[dict]]:
    rng = random.Random(f"{seed}:tickets")
    depts = _quota(rng, DEPT_COUNTS)
    statuses = _quota(rng, STATUS_COUNTS)
    priorities = _quota(rng, PRIORITY_COUNTS)
    staff = {d: staff_of(users, d) for d in DEPT_COUNTS}
    managers = {
        d: next(u for u in users if u.department == d and "dept_manager" in u.roles) for d in staff
    }
    tickets: list[dict] = []
    comments: list[dict] = []
    events: list[dict] = []

    for i in range(1, N_TICKETS + 1):
        dept, status, priority = depts[i - 1], statuses[i - 1], priorities[i - 1]
        requester = rng.choice(users)
        unassigned = status == "open" and rng.random() < 0.4
        assignee = None if unassigned else rng.choice(staff[dept])
        category = rng.choice(CATEGORIES[dept])
        created = REFERENCE_NOW - timedelta(hours=rng.randint(6, 24 * 360))
        title = rng.choice(TITLES[category])
        desc = f"{title}. {' '.join(rng.sample(DETAIL, 2))}"
        has_pii = rng.random() < 0.15
        if has_pii:  # PII giả (đánh dấu synthetic) để thử bộ lọc sau này
            desc += (
                f" Khách hàng {rng.choice(PERSON)}, SĐT 09{rng.randint(10_000_000, 99_999_999)},"
                f" CCCD 001{rng.randint(100_000_000, 999_999_999)}."
            )
        updated = created
        closed_at = closed_by = resolution = None
        if status != "open":
            updated = created + timedelta(hours=rng.randint(2, 24 * 10))
        if status in ("resolved", "closed"):
            resolution = rng.choice(RESOLUTION)
        if status == "closed":
            closed_at = updated
            closed_by = (assignee or managers[dept]).sub
        code = f"TCK-{i:06d}"
        tickets.append(
            {
                "id": i,
                "code": code,
                "title": title,
                "description": desc,
                "status": status,
                "priority": priority,
                "category": category,
                "requester_sub": requester.sub,
                "requester_dept": requester.department,
                "assignee_sub": assignee.sub if assignee else None,
                "assignee_dept": dept,
                "classification": 1,
                "created_at": created,
                "updated_at": updated,
                "closed_at": closed_at,
                "closed_by": closed_by,
                "resolution": resolution,
                "synthetic_pii": has_pii,
            }
        )
        # bình luận (0-3), ~25% internal; tác giả là người yêu cầu hoặc assignee
        for _ in range(rng.randint(0, 3)):
            internal = assignee is not None and rng.random() < 0.25
            author = assignee if (internal or (assignee and rng.random() < 0.6)) else requester
            comments.append(
                {
                    "id": len(comments) + 1,
                    "ticket_id": i,
                    "author_sub": author.sub,
                    "body": rng.choice(INTERNAL if internal else COMMENTS),
                    "internal": internal,
                    "created_at": created + timedelta(minutes=rng.randint(10, 60 * 24 * 3)),
                }
            )
        events.append(
            _event(
                len(events) + 1,
                i,
                requester.sub,
                "create",
                None,
                {"status": "open", "priority": priority},
                created,
            )
        )
        if status != "open":
            actor = (assignee or managers[dept]).sub
            events.append(
                _event(
                    len(events) + 1,
                    i,
                    actor,
                    "status",
                    {"status": "open"},
                    {"status": "in_progress"},
                    created + timedelta(hours=1),
                )
            )
        if status == "closed":
            events.append(
                _event(
                    len(events) + 1,
                    i,
                    closed_by,
                    "close",
                    {"status": "resolved"},
                    {"status": "closed", "resolution": resolution},
                    closed_at,
                )
            )
    return {"tickets": tickets, "comments": comments, "events": events}


def _event(id_, ticket_id, actor, action, before, after, ts):
    return {
        "id": id_,
        "ticket_id": ticket_id,
        "actor_sub": actor,
        "action": action,
        "before": before,
        "after": after,
        "ts": ts,
    }
