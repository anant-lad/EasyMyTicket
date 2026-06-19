#!/usr/bin/env bash
# =============================================================================
# 01_download_all.sh  —  Commercial-Safe Edition
# Downloads every commercially-safe dataset listed in DATASETS.md into ./raw/.
# Total disk needed: ~6 GB compressed + ~15 GB working space during processing.
#
# All datasets here are licensed for proprietary commercial use:
#   - MIT, Apache 2.0, MPL 2.0      → no attribution required for outputs
#   - CC BY 4.0, public domain      → attribution required (see ATTRIBUTION.md)
#
# Run on your g5.12xlarge or any Ubuntu/Debian host.
# =============================================================================

set -euo pipefail

DATA_DIR="${DATA_DIR:-./raw}"
mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

echo "[*] Working directory: $(pwd)"
echo "[*] Free disk: $(df -h . | awk 'NR==2 {print $4}')"

# ---- prerequisites -----------------------------------------------------------
need() { command -v "$1" >/dev/null || { echo "[!] Missing: $1"; MISSING=1; }; }
MISSING=0
need curl; need git; need python3; need unzip
if [ "$MISSING" = "1" ]; then
  echo "[!] Install with:  sudo apt-get install -y curl git python3 python3-pip unzip"
  exit 1
fi

# Install required Python libs if not present
python3 -c "import datasets, huggingface_hub, pandas, openpyxl" 2>/dev/null \
  || pip3 install --user --quiet datasets huggingface_hub pandas pyarrow openpyxl

# ---- helper: download with retry --------------------------------------------
fetch() {  # fetch <url> <output>
  local url="$1" out="$2"
  if [ -f "$out" ] && [ -s "$out" ]; then
    echo "    [skip] $out already present ($(du -h "$out" | cut -f1))"
    return 0
  fi
  echo "    [get]  $url"
  curl -L --fail --retry 5 --retry-delay 10 -C - -o "$out" "$url"
}

hf_snapshot() {  # hf_snapshot <repo_id> <local_subdir>
  local repo="$1" subdir="$2"
  if [ -d "$subdir" ] && [ "$(ls -A "$subdir" 2>/dev/null)" ]; then
    echo "    [skip] $subdir already present"
    return 0
  fi
  python3 - <<PY
from huggingface_hub import snapshot_download
snapshot_download(repo_id="$repo", repo_type="dataset",
                  local_dir="$subdir")
PY
}

# =============================================================================
echo
echo "===== MODULE 1: Ticket Classification ====="
mkdir -p tickets && cd tickets

echo "[1.1] GitBugs (150K real bug reports — Apache/MPL/MIT licensed)"
if [ ! -d "gitbugs" ]; then
  git clone --depth 1 https://github.com/av9ash/gitbugs.git gitbugs
fi

cd ..

# =============================================================================
echo
echo "===== MODULE 2: Skills Taxonomy ====="
mkdir -p skills && cd skills

echo "[2.1] O*NET Computer Occupations (skills DB — public domain)"
fetch "https://www.onetcenter.org/dl_files/database/db_29_0_text.zip" "onet_29_0.zip"
[ -d "onet" ] || (mkdir onet && cd onet && unzip -q ../onet_29_0.zip)

cd ..

# =============================================================================
echo
echo "===== MODULE 3: Conversational Instruction Data ====="
mkdir -p instruction && cd instruction

echo "[3.1] OpenAssistant OASST2 (Apache 2.0)"
fetch "https://huggingface.co/datasets/OpenAssistant/oasst2/resolve/main/2023-11-05_oasst2_ready.messages.jsonl.gz" \
      "oasst2_ready.jsonl.gz"

cd ..

# =============================================================================
echo
echo "===== MODULE 4: NL → Bash / Linux Commands ====="
mkdir -p commands && cd commands

echo "[4.1] NL2Bash (Tellina) — MIT licensed"
fetch "https://raw.githubusercontent.com/TellinaTool/nl2bash/master/data/bash/all.cm" "nl2bash_all.cm"
fetch "https://raw.githubusercontent.com/TellinaTool/nl2bash/master/data/bash/all.nl" "nl2bash_all.nl"

echo "[4.2] NL2SH-ALFA (MIT)"
hf_snapshot "westenfelder/NL2SH-ALFA" "nl2sh_alfa"

echo "[4.3] TLDR pages (CC BY 4.0 — attribution required, see ATTRIBUTION.md)"
fetch "https://github.com/tldr-pages/tldr/archive/refs/heads/main.zip" "tldr_main.zip"
[ -d "tldr-main" ] || unzip -q tldr_main.zip

cd ..

# =============================================================================
echo
echo "===== MODULE 5: Code Bug-Fix Pairs ====="
mkdir -p code_fixes && cd code_fixes

echo "[5.1] SWE-bench (MIT — real GitHub issue → patch)"
hf_snapshot "SWE-bench/SWE-bench_Verified" "swebench_verified"
hf_snapshot "SWE-bench/SWE-bench_Lite" "swebench_lite"
# The full SWE-bench (~50MB metadata) is optional — Verified+Lite is usually enough
# hf_snapshot "SWE-bench/SWE-bench" "swebench_full"

echo "[5.2] CodeXGLUE Java code refinement (C-UDA — permissive)"
hf_snapshot "google/code_x_glue_cc_code_refinement" "code_refinement"

cd ..

# =============================================================================
echo
echo "===== MODULE 6: Real JIRA Project Tickets ====="
mkdir -p jira && cd jira

echo "[6.1] TAWOS — 508K real Jira issues (mostly Apache 2.0 projects)"
if [ ! -d "tawos" ]; then
  git clone --depth 1 https://github.com/SOLAR-group/TAWOS.git tawos
  echo "    NOTE: TAWOS is distributed as a MySQL dump."
  echo "    The build script expects extracted CSVs at: ./tawos/csv_export/"
  echo "    To extract:"
  echo "      docker run --rm -d -e MYSQL_ROOT_PASSWORD=tmp --name tawos-mysql \\"
  echo "        -v \"\$PWD/tawos\":/data mariadb:10"
  echo "      docker exec -i tawos-mysql mysql -uroot -ptmp -e \"CREATE DATABASE tawos;\""
  echo "      docker exec -i tawos-mysql sh -c 'mysql -uroot -ptmp tawos < /data/MySQL_Dump/TAWOS.sql'"
  echo "      mkdir -p tawos/csv_export"
  echo "      docker exec tawos-mysql mysqldump -uroot -ptmp -T /tmp tawos issues"
  echo "      docker cp tawos-mysql:/tmp/issues.txt tawos/csv_export/issues.csv"
fi

echo "[6.2] Apache Jira Social Repository (Apache 2.0)"
if [ ! -d "jira_social" ]; then
  git clone --depth 1 https://github.com/marcoortu/jira-social-repository.git jira_social
fi

cd ..

# =============================================================================
echo
echo "===== ALL DOWNLOADS COMPLETE ====="
echo "Total downloaded:"
du -sh "$DATA_DIR" 2>/dev/null || true
echo
echo "Next steps:"
echo "  1. (Optional) Extract TAWOS MySQL dump to CSV — see commands above"
echo "  2. Run the build:"
echo "     python3 02_build_unified_dataset.py \\"
echo "       --raw ./raw \\"
echo "       --out ./processed \\"
echo "       --your-data /path/to/final_merged_dataset_cleaned.xlsx"
