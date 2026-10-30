"""Corpus tài liệu markdown tiếng Việt (30 tài liệu, 3 nhóm: ALL, SALES, HR) với mức mật trộn lẫn.

Không dùng LLM: nội dung dựng từ khung + ý chính viết tay nên tất định tuyệt đối.
Mỗi tài liệu c2/c3 chứa đúng một canary `ACME-CANARY-<DEPT>-<nnnn>`.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from .users import User, manager_of

NS = uuid.UUID("5d1c0c3e-7a4b-5f0e-9b7d-202610280001")
MGMT_ROLES = ("team_lead", "dept_manager", "management")
HR_SECRET_ROLES = ("dept_manager", "management")
CLASS_LABEL = {0: "Công khai", 1: "Nội bộ", 2: "Mật", 3: "Tối mật"}
SCOPE = {
    0: "Tài liệu công khai, có thể chia sẻ ra bên ngoài công ty.",
    1: "Chỉ lưu hành nội bộ ACME Việt Nam, không chia sẻ ra bên ngoài.",
    2: "Tài liệu mật: chỉ người có quyền truy cập mới được đọc; cấm sao chép ra ngoài hệ thống.",
    3: "Tài liệu tối mật: giới hạn cho nhóm quản lý được chỉ định, mọi truy cập đều được ghi nhận.",
}


@dataclass(frozen=True)
class DocSpec:
    slug: str
    title: str
    department: str  # 'ALL' | 'SALES' | 'HR'
    classification: int
    kind: str
    points: tuple[str, str, str]
    roles: tuple[str, ...] = ()
    table: bool = False
    version: int = 1


def _d(slug, title, dept, cls, kind, points, roles=(), table=False, version=1):
    return DocSpec(slug, title, dept, cls, kind, tuple(points), tuple(roles), table, version)


SPECS: tuple[DocSpec, ...] = (
    # ---- ALL: 3 c0 + 3 c1
    _d(
        "gioi-thieu-acme",
        "Giới thiệu công ty ACME Việt Nam",
        "ALL",
        0,
        "thong_bao",
        [
            "ACME Việt Nam cung cấp giải pháp phần mềm quản trị cho doanh nghiệp vừa và nhỏ.",
            "Công ty có trụ sở tại Hà Nội và chi nhánh tại TP. Hồ Chí Minh.",
            "Giá trị cốt lõi gồm: khách hàng là trung tâm, minh bạch, cải tiến liên tục.",
        ],
    ),
    _d(
        "lich-nghi-le-2026",
        "Thông báo lịch nghỉ lễ năm 2026",
        "ALL",
        0,
        "thong_bao",
        [
            "Nghỉ Tết Nguyên đán theo quy định của Nhà nước, thông báo cụ thể trước 30 ngày.",
            "Các ngày lễ 30/4, 1/5 và Quốc khánh 2/9 nghỉ theo lịch chung.",
            "Bộ phận trực hỗ trợ khách hàng vẫn hoạt động theo ca trực đã đăng ký.",
        ],
        table=True,
    ),
    _d(
        "quy-tac-ung-xu",
        "Bộ quy tắc ứng xử của ACME",
        "ALL",
        0,
        "quy_che",
        [
            "Tôn trọng đồng nghiệp, khách hàng và đối tác trong mọi hoàn cảnh.",
            "Không nhận quà tặng vượt quá giá trị cho phép từ nhà cung cấp.",
            "Báo cáo vi phạm đạo đức qua kênh tiếp nhận ẩn danh của công ty.",
        ],
    ),
    _d(
        "noi-quy-lam-viec",
        "Nội quy làm việc",
        "ALL",
        1,
        "quy_che",
        [
            "Giờ làm việc từ 8h30 đến 17h30, nghỉ trưa 90 phút, thứ Bảy và Chủ nhật nghỉ.",
            "Nhân viên đeo thẻ trong khu vực văn phòng và tuân thủ quy định an ninh.",
            "Làm việc từ xa cần được quản lý trực tiếp phê duyệt trước ít nhất một ngày.",
        ],
    ),
    _d(
        "faq-phuc-loi",
        "FAQ chung về phúc lợi",
        "ALL",
        1,
        "faq",
        [
            "Bảo hiểm sức khoẻ mở rộng áp dụng cho nhân viên sau khi hết thử việc.",
            "Khám sức khoẻ định kỳ mỗi năm một lần tại cơ sở y tế đối tác.",
            "Hỗ trợ ăn trưa theo ngày làm việc thực tế, chi trả cùng kỳ lương.",
        ],
        table=True,
    ),
    _d(
        "dat-phong-hop",
        "Quy trình đặt phòng họp",
        "ALL",
        1,
        "quy_trinh",
        [
            "Đặt phòng qua lịch chung, tối đa hai giờ cho mỗi lượt.",
            "Huỷ lịch trước giờ họp ít nhất 30 phút để nhường phòng cho nhóm khác.",
            "Phòng họp lớn cần đăng ký thiết bị trình chiếu với bộ phận IT.",
        ],
    ),
    # ---- SALES: 1 c0 + 4 c1 + 4 c2 + 3 c3
    _d(
        "sales-bang-gia-cong-khai",
        "Bảng giá công khai các gói dịch vụ",
        "SALES",
        0,
        "bang_gia",
        [
            "Gói Cơ bản có giá từ 1,5 triệu đồng mỗi tháng cho tối đa 10 người dùng.",
            "Gói Nâng cao bổ sung báo cáo và tích hợp, giá từ 4,5 triệu đồng mỗi tháng.",
            "Giá chưa gồm VAT; hợp đồng 12 tháng được tặng 1 tháng sử dụng.",
        ],
        table=True,
    ),
    _d(
        "sales-quy-trinh-bao-gia",
        "Quy trình báo giá chuẩn",
        "SALES",
        1,
        "quy_trinh",
        [
            "Tiếp nhận yêu cầu, xác nhận nhu cầu và quy mô người dùng với khách hàng.",
            "Lập báo giá trên mẫu chuẩn, có hiệu lực 30 ngày kể từ ngày phát hành.",
            "Báo giá vượt ngưỡng chiết khấu thông thường phải được trưởng nhóm duyệt.",
        ],
        version=2,
    ),
    _d(
        "sales-huong-dan-crm",
        "Hướng dẫn sử dụng CRM",
        "SALES",
        1,
        "huong_dan",
        [
            "Mọi cơ hội bán hàng phải được tạo trong CRM trong vòng 24 giờ kể từ lần liên hệ đầu.",
            "Cập nhật giai đoạn cơ hội sau mỗi cuộc gặp với khách hàng.",
            "Không lưu thông tin cá nhân của khách hàng ngoài hệ thống CRM.",
        ],
    ),
    _d(
        "sales-hop-dong-khung",
        "Mẫu hợp đồng khung dịch vụ",
        "SALES",
        1,
        "quy_che",
        [
            "Hợp đồng khung quy định phạm vi dịch vụ, mức độ cam kết dịch vụ và thanh toán.",
            "Mọi sửa đổi điều khoản phải có ý kiến của bộ phận pháp chế.",
            "Hợp đồng được lưu bản gốc tại phòng Kinh doanh trong 10 năm.",
        ],
    ),
    _d(
        "sales-cham-soc-doanh-nghiep",
        "Quy trình chăm sóc khách hàng doanh nghiệp",
        "SALES",
        1,
        "quy_trinh",
        [
            "Mỗi khách hàng doanh nghiệp có một người phụ trách tài khoản cố định.",
            "Họp rà soát định kỳ hằng quý với khách hàng thuộc nhóm Enterprise.",
            "Phản hồi khiếu nại trong vòng 4 giờ làm việc.",
        ],
    ),
    _d(
        "sales-chinh-sach-chiet-khau",
        "Chính sách chiết khấu theo khối lượng",
        "SALES",
        2,
        "chinh_sach",
        [
            "Đơn từ 50 người dùng được chiết khấu tối đa 8 phần trăm trên giá niêm yết.",
            "Đơn từ 200 người dùng cần phê duyệt của trưởng phòng Kinh doanh.",
            "Không công khai bảng chiết khấu cho khách hàng trước khi ký thoả thuận bảo mật.",
        ],
        table=True,
    ),
    _d(
        "sales-bao-cao-doanh-so-q3",
        "Báo cáo doanh số quý 3 năm 2026",
        "SALES",
        2,
        "bao_cao_noi_bo",
        [
            "Doanh số quý 3 tăng so với cùng kỳ nhờ nhóm khách hàng SMB.",
            "Khu vực miền Nam đóng góp tỷ trọng lớn nhất trong tổng doanh thu.",
            "Tỷ lệ huỷ đơn giữ ở mức thấp, tập trung ở nhóm khách hàng Retail.",
        ],
        roles=MGMT_ROLES,
        table=True,
    ),
    _d(
        "sales-khach-hang-chien-luoc",
        "Danh sách khách hàng chiến lược",
        "SALES",
        2,
        "bao_cao_noi_bo",
        [
            "Danh sách gồm các khách hàng Enterprise có giá trị hợp đồng cao nhất năm.",
            "Mỗi khách hàng chiến lược có kế hoạch chăm sóc riêng do trưởng phòng phê duyệt.",
            "Thông tin liên hệ không được chia sẻ ngoài nhóm phụ trách.",
        ],
    ),
    _d(
        "sales-phe-duyet-hop-dong-lon",
        "Quy trình phê duyệt hợp đồng trên 500 triệu",
        "SALES",
        2,
        "quy_trinh",
        [
            "Hợp đồng trên 500 triệu đồng cần thẩm định rủi ro tín dụng của khách hàng.",
            "Phê duyệt hai cấp: trưởng phòng Kinh doanh và khối Tài chính.",
            "Ghi nhận mọi ngoại lệ về điều khoản thanh toán vào hồ sơ phê duyệt.",
        ],
    ),
    _d(
        "sales-ke-hoach-kinh-doanh-2027",
        "Kế hoạch kinh doanh năm 2027",
        "SALES",
        3,
        "ke_hoach_kinh_doanh",
        [
            "Mục tiêu doanh thu năm 2027 tăng mạnh so với năm 2026 dựa trên hai dòng sản phẩm mới.",
            "Ngân sách tiếp thị tập trung vào kênh đối tác và hội thảo chuyên ngành.",
            "Kế hoạch tuyển dụng thêm đội ngũ bán hàng tại khu vực miền Trung.",
        ],
        table=True,
    ),
    _d(
        "sales-chien-luoc-dinh-gia-2027",
        "Chiến lược định giá cạnh tranh 2027",
        "SALES",
        3,
        "ke_hoach_kinh_doanh",
        [
            "Định giá thâm nhập thấp hơn đối thủ chính ở phân khúc SMB trong sáu tháng đầu.",
            "Giữ nguyên giá nhóm Enterprise, cạnh tranh bằng dịch vụ đi kèm.",
            "Không để lộ chiến lược giá trước thời điểm công bố chính thức.",
        ],
    ),
    _d(
        "sales-mo-rong-mien-trung",
        "Kế hoạch mở rộng thị trường khu vực miền Trung",
        "SALES",
        3,
        "ke_hoach_kinh_doanh",
        [
            "Mở văn phòng đại diện tại Đà Nẵng vào quý 2 năm 2027.",
            "Đàm phán với hai đối tác phân phối địa phương, chưa công bố tên.",
            "Ngân sách đầu tư giai đoạn một do ban giám đốc phê duyệt.",
        ],
    ),
    # ---- HR: 1 c0 + 4 c1 + 4 c2 + 3 c3
    _d(
        "hr-thong-tin-tuyen-dung",
        "Thông tin tuyển dụng công khai",
        "HR",
        0,
        "thong_bao",
        [
            "ACME tuyển dụng các vị trí kỹ sư phần mềm, chuyên viên kinh doanh và chăm sóc khách hàng.",
            "Hồ sơ gửi về hòm thư tuyển dụng của công ty, không nhận hồ sơ qua tin nhắn cá nhân.",
            "Quy trình gồm sàng lọc hồ sơ, phỏng vấn hai vòng và đề xuất thư mời nhận việc.",
        ],
    ),
    _d(
        "hr-quy-che-lao-dong",
        "Quy chế lao động",
        "HR",
        1,
        "quy_che",
        [
            "Thời gian thử việc tối đa 60 ngày đối với vị trí chuyên viên.",
            "Nhân viên được hưởng 12 ngày phép năm, tăng thêm theo thâm niên.",
            "Chấm dứt hợp đồng phải báo trước theo quy định của pháp luật lao động.",
        ],
        version=2,
    ),
    _d(
        "hr-quy-trinh-nghi-phep",
        "Quy trình nghỉ phép",
        "HR",
        1,
        "quy_trinh",
        [
            "Gửi đề nghị nghỉ phép trên hệ thống ít nhất ba ngày làm việc trước ngày nghỉ.",
            "Quản lý trực tiếp phê duyệt trong vòng hai ngày làm việc.",
            "Nghỉ ốm cần nộp giấy xác nhận của cơ sở y tế trong vòng bảy ngày.",
        ],
    ),
    _d(
        "hr-onboarding",
        "Quy trình onboarding nhân viên mới",
        "HR",
        1,
        "quy_trinh",
        [
            "Chuẩn bị thiết bị, tài khoản và thẻ ra vào trước ngày nhận việc.",
            "Buổi định hướng ngày đầu giới thiệu văn hoá, nội quy và quy trình bảo mật.",
            "Người hướng dẫn được phân công đồng hành trong 30 ngày đầu.",
        ],
    ),
    _d(
        "hr-chinh-sach-dao-tao",
        "Chính sách đào tạo nội bộ",
        "HR",
        1,
        "chinh_sach",
        [
            "Mỗi nhân viên có ngân sách đào tạo hằng năm theo cấp bậc.",
            "Khoá học bên ngoài cần được quản lý duyệt và cam kết chia sẻ lại nội dung.",
            "Chứng chỉ chuyên môn được hoàn lại chi phí sau khi thi đạt.",
        ],
    ),
    _d(
        "hr-chinh-sach-thuong-kpi",
        "Chính sách thưởng KPI năm 2026",
        "HR",
        2,
        "chinh_sach",
        [
            "Thưởng KPI tính theo mức hoàn thành mục tiêu cá nhân và mục tiêu phòng ban.",
            "Mức thưởng tối đa tương đương hai tháng lương cơ bản.",
            "Thưởng được chi trả cùng kỳ lương tháng 1 năm sau.",
        ],
        table=True,
    ),
    _d(
        "hr-danh-gia-hieu-suat",
        "Quy trình đánh giá hiệu suất",
        "HR",
        2,
        "quy_trinh",
        [
            "Đánh giá hai lần mỗi năm, vào tháng 6 và tháng 12.",
            "Kết quả đánh giá gồm bốn mức, ảnh hưởng đến điều chỉnh lương và thưởng.",
            "Nhân viên có quyền phản hồi và đề nghị xem xét lại kết quả đánh giá.",
        ],
        roles=MGMT_ROLES,
    ),
    _d(
        "hr-phuc-loi-mo-rong",
        "Chính sách phúc lợi mở rộng",
        "HR",
        2,
        "chinh_sach",
        [
            "Gói bảo hiểm sức khoẻ mở rộng cho người thân, chi phí chia sẻ giữa công ty và nhân viên.",
            "Hỗ trợ học phí cho con em nhân viên có thâm niên trên ba năm.",
            "Điều kiện áp dụng do phòng Nhân sự xét duyệt từng trường hợp.",
        ],
    ),
    _d(
        "hr-xu-ly-khieu-nai-lao-dong",
        "Hướng dẫn xử lý khiếu nại lao động",
        "HR",
        2,
        "huong_dan",
        [
            "Tiếp nhận khiếu nại bằng văn bản, phản hồi xác nhận trong hai ngày làm việc.",
            "Thành lập nhóm xác minh gồm đại diện Nhân sự và một quản lý độc lập.",
            "Giữ bí mật danh tính người khiếu nại trong suốt quá trình xử lý.",
        ],
    ),
    _d(
        "hr-bang-bac-luong-2026",
        "Bảng bậc lương năm 2026",
        "HR",
        3,
        "chinh_sach",
        [
            "Bảng bậc lương chia theo bảy bậc, mỗi bậc có khung lương tối thiểu và tối đa.",
            "Lương của vị trí quản lý cấp cao chỉ được công bố cho ban giám đốc.",
            "Mọi điều chỉnh ngoài khung phải có phê duyệt của giám đốc điều hành.",
        ],
        roles=HR_SECRET_ROLES,
        table=True,
    ),
    _d(
        "hr-ho-so-ky-luat-mau",
        "Hồ sơ kỷ luật mẫu (đã ẩn danh)",
        "HR",
        3,
        "bao_cao_noi_bo",
        [
            "Hồ sơ mẫu minh hoạ quy trình xử lý vi phạm nội quy mức độ nghiêm trọng.",
            "Tên người liên quan được thay bằng mã ẩn danh, không thể truy ngược.",
            "Chỉ dùng cho đào tạo quản lý, không lưu hành rộng.",
        ],
        roles=HR_SECRET_ROLES,
    ),
    _d(
        "hr-dieu-chinh-luong-2027",
        "Kế hoạch điều chỉnh lương năm 2027",
        "HR",
        3,
        "ke_hoach_kinh_doanh",
        [
            "Ngân sách điều chỉnh lương năm 2027 dự kiến tăng nhẹ so với năm 2026.",
            "Ưu tiên nhóm nhân sự kỹ thuật có kết quả đánh giá cao.",
            "Chưa thông báo cho nhân viên cho đến khi ban giám đốc phê duyệt.",
        ],
        roles=HR_SECRET_ROLES,
    ),
)


def owner_for(dept: str, users: list[User]) -> User:
    if dept == "ALL":
        return next(u for u in users if "admin" in u.roles)
    return manager_of(users, dept)


def render(spec: DocSpec, canary: str | None) -> str:
    lines = [
        f"# {spec.title}",
        "",
        f"- Phòng ban: {spec.department}",
        f"- Mức mật: {CLASS_LABEL[spec.classification]} (classification={spec.classification})",
        f"- Phiên bản: {spec.version}",
        f"- Loại tài liệu: {spec.kind}",
        "",
        "## Mục đích",
        "",
        f"Tài liệu này quy định và hướng dẫn nội dung liên quan đến: {spec.title.lower()}. "
        "Áp dụng cho các bộ phận có liên quan tại ACME Việt Nam.",
        "",
        "## Nội dung chính",
        "",
    ]
    lines += [f"{i}. {p}" for i, p in enumerate(spec.points, 1)]
    if spec.table:
        lines += [
            "",
            "## Bảng tóm tắt",
            "",
            "| Hạng mục | Nội dung | Ghi chú |",
            "|---|---|---|",
        ]
        lines += [
            f"| Mục {i} | {p.split(',')[0].rstrip('.')} | Xem phần nội dung chính |"
            for i, p in enumerate(spec.points, 1)
        ]
    lines += ["", "## Phạm vi áp dụng", "", SCOPE[spec.classification]]
    if canary:
        lines += ["", f"Mã tham chiếu kiểm soát: {canary}"]
    return "\n".join(lines) + "\n"


def build_docs(users: list[User]) -> list[dict]:
    """Trả về danh sách dict metadata + nội dung (thứ tự cố định)."""
    counters: dict[str, int] = {}
    out = []
    for spec in SPECS:
        canary = None
        if spec.classification >= 2:
            counters[spec.department] = counters.get(spec.department, 0) + 1
            canary = f"ACME-CANARY-{spec.department}-{counters[spec.department]:04d}"
        text = render(spec, canary)
        raw = text.encode("utf-8")
        out.append(
            {
                "id": str(uuid.uuid5(NS, f"acme-doc/{spec.slug}")),
                "slug": spec.slug,
                "title": spec.title,
                "source_path": f"corpus/{spec.department}/{spec.slug}.md",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "department": spec.department,
                "classification": spec.classification,
                "allowed_roles": list(spec.roles),
                "owner_sub": owner_for(spec.department, users).sub,
                "version": spec.version,
                "kind": spec.kind,
                "canary": canary,
                "content": text,
            }
        )
    return out
