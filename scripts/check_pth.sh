#!/usr/bin/env bash
# Liệt kê *.pth, sitecustomize.py, usercustomize.py trong site-packages của venv;
# fail nếu ngoài allowlist (eval/security/pth-allowlist.txt, mỗi dòng một glob tên file).
# Dùng: bash eval/security/check_pth.sh [venv_dir=.venv]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="${1:-.venv}"
allow="${PTH_ALLOWLIST:-$here/pth-allowlist.txt}"

if [ ! -d "$venv" ]; then echo "check_pth: không thấy venv '$venv'" >&2; exit 2; fi

allowed=()
while IFS= read -r line; do
  line="${line%$'\r'}"
  case "$line" in ''|'#'*) continue ;; esac
  allowed+=("$line")
done < "$allow"

bad=0
while IFS= read -r f; do
  name="$(basename "$f")"
  ok=0
  for pat in "${allowed[@]}"; do
    # shellcheck disable=SC2254
    case "$name" in $pat) ok=1; break ;; esac
  done
  if [ "$ok" -eq 1 ]; then echo "ok      $f"; else echo "DENIED  $f"; bad=1; fi
done < <(find "$venv" -type d -name site-packages -exec find {} -maxdepth 1 -type f \
           \( -name '*.pth' -o -name 'sitecustomize.py' -o -name 'usercustomize.py' \) \; | sort)

if [ "$bad" -ne 0 ]; then echo "check_pth: file khởi động ngoài allowlist" >&2; exit 1; fi
echo "check_pth: OK"
