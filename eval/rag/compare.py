"""So sánh các cấu hình trong một `report.json` của `run`: chênh lệch theo cặp và kiểm tra quá khớp.

Chạy: `uv run --all-packages python -m eval.rag compare <report.json> [--baseline hybrid]
[--metric recall@5] [--select hybrid@wfts0.5,hybrid@wfts0.25,hybrid@wfts0.1]`.

- Chênh lệch theo cặp: mean(cấu hình - baseline) và khoảng bootstrap 95% theo cặp trên cùng 40 câu.
  Khoảng không chứa 0 mới đáng xét; chưa chứa 0 nghĩa là chưa phân biệt được ở cỡ mẫu này.
- `--select`: chọn một tham số trong danh sách bằng điểm trên nửa này của bộ câu, đo trên nửa kia
  (chia theo thứ tự câu: chẵn/lẻ), rồi đổi vai. Cho thấy tham số chọn trên 20 câu có giữ điểm
  trên 20 câu còn lại không; 40 câu quá ít để chọn tham số một cách tin cậy.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from . import metrics


def _scores(report: dict, config: str, metric: str) -> dict[str, float]:  # type: ignore[type-arg]
    rows = report["configs"][config]["per_question"]
    return {r["id"]: float(r["scores"][metric]) for r in rows}


def paired_table(report: dict, baseline: str, metric: str) -> str:  # type: ignore[type-arg]
    base = _scores(report, baseline, metric)
    ids = sorted(base)
    lines = [f"{'cấu hình':<30}{metric:>10}{'CI95':>18}{'Δ so với ' + baseline:>22}{'CI95 Δ':>18}"]
    for name in report["configs"]:
        s = _scores(report, name, metric)
        a = [s[i] for i in ids]
        lo, hi = metrics.bootstrap_ci(a)
        d, dlo, dhi = metrics.paired_bootstrap_delta(a, [base[i] for i in ids])
        lines.append(
            f"{name:<30}{statistics.fmean(a):>10.3f}{f'[{lo:.3f}, {hi:.3f}]':>18}"
            f"{d:>+22.3f}{f'[{dlo:+.3f}, {dhi:+.3f}]':>18}"
        )
    return "\n".join(lines)


def split_half(report: dict, candidates: list[str], metric: str) -> list[dict[str, object]]:  # type: ignore[type-arg]
    """Với mỗi nửa: chọn cấu hình tốt nhất ở nửa đó, đo ở nửa kia."""
    per = {c: _scores(report, c, metric) for c in candidates}
    ids = sorted(next(iter(per.values())))
    halves = {"chan": ids[0::2], "le": ids[1::2]}
    out: list[dict[str, object]] = []
    for sel, other in (("chan", "le"), ("le", "chan")):
        mean_sel = {c: statistics.fmean(per[c][i] for i in halves[sel]) for c in candidates}
        best = max(candidates, key=lambda c: (mean_sel[c], -candidates.index(c)))
        out.append(
            {
                "chon_tren": sel,
                "chon": best,
                "diem_tren_nua_chon": mean_sel[best],
                "diem_tren_nua_con_lai": statistics.fmean(per[best][i] for i in halves[other]),
                "diem_moi_ung_vien_tren_nua_con_lai": {
                    c: statistics.fmean(per[c][i] for i in halves[other]) for c in candidates
                },
            }
        )
    return out


def run(path: str, baseline: str, metric: str, select: list[str]) -> str:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    parts = [paired_table(report, baseline, metric)]
    if select:
        parts.append("\nKiểm tra quá khớp (chọn trên một nửa, đo trên nửa kia):")
        parts.append(json.dumps(split_half(report, select, metric), ensure_ascii=False, indent=2))
    return "\n".join(parts)
