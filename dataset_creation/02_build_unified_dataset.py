#!/usr/bin/env python3
"""
02_build_unified_dataset.py  —  Commercial-Safe Edition
========================================================
Reads commercially-safe raw datasets from ./raw/, normalizes each into a
common schema, and writes four training-ready JSONL files into ./processed/:

    classification.jsonl    — for fine-tuning the ticket classifier
                              {"text", "labels": {"priority","category","type"}}
    skill_assignment.jsonl  — for fine-tuning the skill router
                              {"ticket", "required_skills":[...]}
    resolution.jsonl        — for fine-tuning resolution generation (RAG-augmented)
                              {"problem", "resolution"}
    instruction.jsonl       — for fine-tuning command/code/debug behavior
                              {"instruction", "input", "output"}

This version EXCLUDES the following sources due to license incompatibility
with proprietary commercial release:
    - Tobi-Bueck customer support tickets (CC-BY-NC)
    - Stack Exchange data dumps (CC-BY-SA, share-alike)
    - Databricks Dolly 15K (CC-BY-SA, share-alike)

Run on a host with >=32 GB RAM. Tested on Python 3.10+.

Usage:
    python3 02_build_unified_dataset.py \\
        --raw   ./raw \\
        --out   ./processed \\
        --your-data /path/to/final_merged_dataset_cleaned.xlsx
"""

import argparse
import gzip
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import pandas as pd

# ----------------------------------------------------------------------------
#  Schema and skill taxonomy
# ----------------------------------------------------------------------------

PRIORITY_LEVELS = ["low", "medium", "high", "critical"]

CATEGORIES = [
    "hardware", "software", "network", "security", "account_access",
    "database", "cloud_infrastructure", "performance", "backup_recovery",
    "email_collaboration", "operating_system", "application_dev",
    "deployment_devops", "data_loss", "billing", "feature_request",
    "general_inquiry", "other",
]

# Autotask ISSUETYPE numeric ID → dataset category.
# Derived from smart_ticket_assignment.py skill mappings + sample titles.
ISSUETYPE_CATEGORY: Dict[str, str] = {
    "4":  "hardware",             # Hardware, Assessment (laptop issues, config items)
    "5":  "software",             # Software, Installation, SaaS (QuickBooks, app updates)
    "6":  "network",              # Network, VPN, Remote Access (uplink alerts, connectivity)
    "7":  "general_inquiry",      # General assessment calls
    "8":  "software",             # Server administration, deployment
    "9":  "account_access",       # Active Directory, onboarding/offboarding
    "10": "email_collaboration",  # VoIP/NEXTIVA, email on device
    "11": "cloud_infrastructure", # Cloud Workspace, Office 365, SharePoint, OneDrive
    "12": "hardware",             # Phone/device hardware setup
    "13": "backup_recovery",      # Backup, DATTO, disaster recovery
    "14": "security",             # Cybersecurity, dark web monitoring
    "15": "email_collaboration",  # Email domain statistics, email security
    "16": "hardware",             # Keyboard and peripheral hardware
    "17": "general_inquiry",      # Urgent callbacks, general help requests
    "18": "hardware",             # Printer, printing hardware
    "19": "software",             # Software licensing (Microsoft, SaaS)
    "20": "security",             # AV/antivirus deployment, security tools
    "21": "billing",              # Invoices, time entries, billing
    "22": "security",             # SSL/TLS certificate management
    "23": "account_access",       # Password resets, MFA resets
    "25": "security",             # Sophos/firewall security alerts
    "26": "general_inquiry",      # Welcome calls, onboarding requests
}

# Skill taxonomy — derived from O*NET Computer Occupations + heuristics.
# Each skill maps to regex patterns that signal it in ticket text.
SKILL_RULES = {
    "linux_admin":     [r"\b(linux|ubuntu|debian|rhel|centos|systemd|cron|bash)\b"],
    "windows_admin":   [r"\b(windows|powershell|active.directory|gpo|wmi|registry)\b"],
    "networking":      [r"\b(tcp|udp|dns|dhcp|vpn|firewall|router|switch|vlan|subnet|nat|iptables)\b"],
    "database":        [r"\b(mysql|postgres(?:ql)?|sql[\s-]?server|oracle\s+db|oracle\s+sql|mongodb|redis|sqlite|mariadb|t-sql|pl[/-]?sql|elasticsearch|cassandra)\b"],
    "security":        [r"\b(security|vulnerab|cve|exploit|malware|ransom|phishing|ssl|tls|certificate|firewall|ids|ips)\b"],
    "cloud_aws":       [r"\b(aws|ec2|s3|rds|lambda|iam|cloudwatch|vpc|cloudformation)\b"],
    "cloud_azure":     [r"\b(azure|aks|cosmosdb|entra|intune|defender)\b"],
    "cloud_gcp":       [r"\b(gcp|gke|bigquery|pub.sub|firebase)\b"],
    "containers":      [r"\b(docker|kubernetes|k8s|helm|podman|containerd)\b"],
    "devops_ci":       [r"\b(jenkins|gitlab.ci|github.actions|ansible|terraform|puppet|chef)\b"],
    "scripting":       [r"\b(bash|shell|python|perl|powershell|awk|sed)\b"],
    "programming":     [r"\b(java|python|javascript|c\+\+|c#|go|rust|ruby|php|kotlin|swift)\b"],
    "frontend":        [r"\b(html|css|react|vue|angular|javascript|typescript)\b"],
    "backend":         [r"\b(api|rest|graphql|microservice|spring|express|django|flask|fastapi)\b"],
    "hardware_drivers":[r"\b(driver|firmware|bios|uefi|nvidia|amd|intel|graphics|gpu|sound|audio|bluetooth|wifi|wireless|usb)\b"],
    "email":           [r"\b(outlook|exchange|smtp|imap|pop3|spam|email|gmail)\b"],
    "vpn_remote":      [r"\b(vpn|remote.desktop|rdp|ssh|teamviewer|anydesk)\b"],
    "backup":          [r"\b(backup|restore|veeam|acronis|snapshot|recovery)\b"],
    "monitoring":      [r"\b(monitor|nagios|zabbix|prometheus|grafana|datadog|splunk|elk)\b"],
    "virtualization":  [r"\b(vmware|esxi|hyper-v|kvm|virtualbox|vagrant)\b"],
    "version_control": [r"\b(git|github|gitlab|bitbucket|svn|merge.request|pull.request)\b"],
}
SKILL_NAMES = sorted(SKILL_RULES.keys())
SKILL_COMPILED = {k: [re.compile(p, re.I) for p in pats] for k, pats in SKILL_RULES.items()}


def detect_skills(text: str) -> List[str]:
    """Return list of skills required, given ticket title+description."""
    if not text:
        return []
    return sorted({s for s, pats in SKILL_COMPILED.items() if any(p.search(text) for p in pats)})


def normalize_priority(value) -> str:
    """Map any source's priority encoding to {low,medium,high,critical}."""
    if value is None:
        return "medium"
    s = str(value).strip().lower()
    if s in {"1", "5", "critical", "blocker", "p1", "urgent"}:
        return "critical"
    if s in {"2", "4", "high", "major", "p2"}:
        return "high"
    if s in {"3", "medium", "normal", "p3"}:
        return "medium"
    if s in {"low", "minor", "trivial", "p4", "p5"}:
        return "low"
    try:
        n = int(float(s))
        if n <= 1:  return "critical"
        if n == 2:  return "high"
        if n == 3:  return "medium"
        return "low"
    except (ValueError, TypeError):
        return "medium"


def normalize_category(raw) -> str:
    """Best-effort normalization of project/component/category strings."""
    if raw is None: return "other"
    s = str(raw).lower().strip()
    if any(t in s for t in ["hardware", "device", "physical"]): return "hardware"
    if any(t in s for t in ["network", "connectivity", "vpn", "dns"]): return "network"
    if any(t in s for t in ["security", "auth", "permission", "vuln"]): return "security"
    if any(t in s for t in ["database", "db ", "sql"]): return "database"
    if any(t in s for t in ["backup", "restore", "recovery"]): return "backup_recovery"
    if any(t in s for t in ["email", "outlook", "exchange", "mail"]): return "email_collaboration"
    if any(t in s for t in ["performance", "slow", "latency"]): return "performance"
    if any(t in s for t in ["cloud", "aws", "azure", "gcp"]): return "cloud_infrastructure"
    if any(t in s for t in ["account", "login", "password"]): return "account_access"
    if any(t in s for t in ["bug", "error", "crash", "exception"]): return "software"
    if any(t in s for t in ["feature", "enhancement", "improvement"]): return "feature_request"
    return "software"  # bug-tracker default


# ----------------------------------------------------------------------------
#  HTML/markup utilities (used by GitBugs and Jira parsers)
# ----------------------------------------------------------------------------

def strip_html(s: str) -> str:
    """Crude HTML→text. Keeps <code> and <pre> blocks fenced as markdown."""
    if not s: return ""
    s = re.sub(r"<pre><code>(.*?)</code></pre>", r"\n```\n\1\n```\n", s, flags=re.S)
    s = re.sub(r"<code>(.*?)</code>", r"`\1`", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = (s.replace("&lt;", "<").replace("&gt;", ">")
           .replace("&amp;", "&").replace("&quot;", '"').replace("&#x27;", "'"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ----------------------------------------------------------------------------
#  JSONL writer
# ----------------------------------------------------------------------------

class JsonlWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.fh = open(path, "w", encoding="utf-8")
        self.count = 0

    def write(self, obj: dict):
        self.fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.count += 1

    def close(self):
        self.fh.close()
        print(f"    [out] {self.path}  ({self.count:,} rows)")


# ----------------------------------------------------------------------------
#  Source parsers
# ----------------------------------------------------------------------------

def parse_user_xlsx(path: Optional[str]) -> Iterator[Dict]:
    """User's existing 162K MSP ticket dataset — keep only Real rows."""
    if not path or not os.path.exists(path):
        return
    print(f"    [user_msp] reading {path}")
    df = pd.read_excel(path)
    if "DATA_SOURCE" in df.columns:
        df = df[df["DATA_SOURCE"].astype(str).str.lower() == "real"]
    # else: all rows are real (pre-cleaned file)
    for _, row in df.iterrows():
        title = str(row.get("TITLE", "") or "")
        desc = str(row.get("DESCRIPTION", "") or "")
        res = str(row.get("RESOLUTION", "") or "")
        if len(title) + len(desc) < 30:
            continue
        issuetype_raw = row.get("ISSUETYPE")
        try:
            it_key = str(int(float(issuetype_raw))) if issuetype_raw is not None and str(issuetype_raw) != "nan" else ""
        except (ValueError, TypeError):
            it_key = str(issuetype_raw).strip()
        category = ISSUETYPE_CATEGORY.get(it_key) or normalize_category(title + " " + desc)
        yield {
            "_source": "user_msp_real",
            "_kind": "ticket_resolved",
            "title": title[:250],
            "description": desc[:5000],
            "resolution": res[:5000] if res and res != "nan" else "",
            "priority": normalize_priority(row.get("PRIORITY")),
            "category": category,
            "issuetype_id": it_key,
        }


def parse_gitbugs(root: Path) -> Iterator[Dict]:
    """
    GitBugs: 150K real bug reports across 9 OSS projects.
    The repo lays out per-project CSVs; layout varies, so we scan recursively.
    Expected fields (per the GitBugs paper): Summary, Description, Status,
    Priority, Resolution. Different projects use slightly different column
    spellings — we tolerate variations.
    """
    if not root.exists():
        return

    # Recognized field aliases (all lowercased for comparison)
    ALIAS = {
        "summary":     ["summary", "title", "issue_title"],
        "description": ["description", "body", "issue_body", "details"],
        "status":      ["status", "state", "issue_state"],
        "priority":    ["priority", "severity"],
        "resolution":  ["resolution", "fix", "fixed_in", "resolution_text", "comments"],
        "project":     ["project", "repo", "repository", "product", "component"],
        "type":        ["type", "issue_type", "labels", "kind"],
    }

    def find_col(df_cols, key):
        cmap = {c.lower(): c for c in df_cols}
        for alias in ALIAS[key]:
            if alias in cmap:
                return cmap[alias]
        return None

    csvs = list(root.rglob("*.csv"))
    print(f"    [gitbugs] found {len(csvs)} CSV files")
    for csv in csvs:
        # Skip helper/metadata CSVs (these are typically <50 KB)
        if csv.stat().st_size < 50_000:
            continue
        try:
            df = pd.read_csv(csv, low_memory=False, on_bad_lines="skip")
        except Exception as e:
            print(f"        [warn] could not read {csv}: {e}")
            continue
        cols = list(df.columns)
        c_summary = find_col(cols, "summary")
        c_desc    = find_col(cols, "description")
        c_status  = find_col(cols, "status")
        c_priority = find_col(cols, "priority")
        c_resolution = find_col(cols, "resolution")
        c_type    = find_col(cols, "type")

        if not c_summary and not c_desc:
            continue  # not a bug-report style CSV

        project_name = csv.parent.name.lower() or "gitbugs"

        for _, row in df.iterrows():
            title = str(row.get(c_summary, "") if c_summary else "")
            desc  = str(row.get(c_desc, "") if c_desc else "")
            title = strip_html(title)[:250]
            desc  = strip_html(desc)[:5000]
            if len(title) + len(desc) < 30:
                continue

            res = ""
            if c_resolution:
                res = strip_html(str(row.get(c_resolution, "") or ""))[:5000]
                if res.lower() in {"nan", "none", "fixed", "duplicate", "invalid", "unresolved"}:
                    res = ""  # status-only resolution is not a real fix description

            type_raw = str(row.get(c_type, "") if c_type else "issue").lower()
            ttype = "bug" if any(t in type_raw for t in ["bug", "defect"]) else "issue"

            yield {
                "_source": f"gitbugs_{project_name}",
                "_kind": "ticket_labeled" if c_priority else "ticket_resolved",
                "title": title,
                "description": desc,
                "resolution": res,
                "priority": normalize_priority(row.get(c_priority) if c_priority else None),
                "category": normalize_category(row.get(c_type) if c_type else "software"),
                "type": ttype,
                "tags": [project_name],
            }


def parse_oasst2(path: Path) -> Iterator[Dict]:
    """OpenAssistant — keep technical prompter→assistant pairs (Apache 2.0)."""
    if not path.exists():
        return
    print(f"    [oasst2] reading {path}")
    msgs_by_id = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            m = json.loads(line)
            msgs_by_id[m["message_id"]] = m

    tech_keywords = re.compile(
        r"\b(linux|bash|ssh|docker|python|java|sql|server|kernel|driver|"
        r"network|debug|error|install|configure|script|terminal|api|"
        r"git|database|deploy|kubernetes|fix|crash|exception)\b", re.I)

    for m in msgs_by_id.values():
        if m.get("role") != "assistant" or not m.get("parent_id"):
            continue
        parent = msgs_by_id.get(m["parent_id"])
        if not parent or parent.get("role") != "prompter":
            continue
        prompt = parent.get("text", "")
        response = m.get("text", "")
        if not (tech_keywords.search(prompt) or tech_keywords.search(response)):
            continue
        if m.get("lang") and m["lang"] != "en":
            continue
        yield {
            "_source": "oasst2",
            "_kind": "instruction",
            "instruction": prompt[:3000],
            "input": "",
            "output": response[:5000],
        }


def parse_nl2bash(cm_path: Path, nl_path: Path) -> Iterator[Dict]:
    """NL2Bash: parallel command/description files (MIT)."""
    if not (cm_path.exists() and nl_path.exists()):
        return
    print(f"    [nl2bash] reading {cm_path.name} + {nl_path.name}")
    with open(cm_path, encoding="utf-8") as f1, open(nl_path, encoding="utf-8") as f2:
        for cmd, nl in zip(f1, f2):
            cmd, nl = cmd.strip(), nl.strip()
            if not cmd or not nl:
                continue
            yield {
                "_source": "nl2bash",
                "_kind": "instruction",
                "instruction": nl,
                "input": "",
                "output": f"```bash\n{cmd}\n```",
            }


def parse_nl2sh_alfa(root: Path) -> Iterator[Dict]:
    """NL2SH-ALFA from HuggingFace snapshot (MIT)."""
    if not root.exists():
        return
    print(f"    [nl2sh_alfa] scanning {root}")
    for parquet in root.rglob("*.parquet"):
        try:
            df = pd.read_parquet(parquet)
        except Exception:
            continue
        cols = {c.lower(): c for c in df.columns}
        c_nl = cols.get("nl") or cols.get("description") or cols.get("instruction")
        c_cmd = cols.get("bash") or cols.get("command") or cols.get("cmd") or cols.get("output")
        if not c_nl or not c_cmd:
            continue
        for _, row in df.iterrows():
            nl, cmd = str(row[c_nl]).strip(), str(row[c_cmd]).strip()
            if not nl or not cmd:
                continue
            yield {
                "_source": "nl2sh_alfa",
                "_kind": "instruction",
                "instruction": nl,
                "input": "",
                "output": f"```bash\n{cmd}\n```",
            }


def parse_tldr(root: Path) -> Iterator[Dict]:
    """TLDR pages — community man-page summaries (CC BY 4.0, attribution required)."""
    pages_dir = root / "pages"
    if not pages_dir.exists():
        pages_dir = next(root.rglob("pages"), None)
    if not pages_dir or not pages_dir.exists():
        return
    print(f"    [tldr] scanning {pages_dir}")

    for md in pages_dir.rglob("*.md"):
        try:
            content = md.read_text(encoding="utf-8")
        except Exception:
            continue
        match = re.match(r"# (\S[\S\s]*?)\n+>\s*([^\n]+)", content)
        if not match:
            continue
        cmd_name = match.group(1).strip()
        for ex_desc, ex_cmd in re.findall(r"-\s*([^:\n]+):\s*\n+`([^`]+)`", content):
            yield {
                "_source": "tldr",
                "_kind": "instruction",
                "instruction": f"{ex_desc.strip()} (using {cmd_name})",
                "input": "",
                "output": f"```bash\n{ex_cmd.strip()}\n```",
            }


def parse_code_refinement(root: Path) -> Iterator[Dict]:
    """CodeXGLUE Java code refinement — buggy → fixed pairs (C-UDA)."""
    if not root.exists():
        return
    print(f"    [code_refinement] scanning {root}")
    for parquet in root.rglob("*.parquet"):
        try:
            df = pd.read_parquet(parquet)
        except Exception:
            continue
        for _, row in df.iterrows():
            buggy = str(row.get("buggy", ""))
            fixed = str(row.get("fixed", ""))
            if not buggy or not fixed or buggy == fixed:
                continue
            yield {
                "_source": "codexglue_refinement",
                "_kind": "instruction",
                "instruction": "Fix the bug in the following Java function:",
                "input": f"```java\n{buggy}\n```",
                "output": f"```java\n{fixed}\n```",
            }


def parse_swebench(root: Path) -> Iterator[Dict]:
    """SWE-bench: real GitHub issue → patch (MIT)."""
    if not root.exists():
        return
    print(f"    [swebench] scanning {root}")
    for parquet in root.rglob("*.parquet"):
        try:
            df = pd.read_parquet(parquet)
        except Exception:
            continue
        for _, row in df.iterrows():
            problem = str(row.get("problem_statement", "") or "")
            patch = str(row.get("patch", "") or "")
            if not problem or not patch:
                continue
            yield {
                "_source": "swebench",
                "_kind": "instruction",
                "instruction": "Fix the issue described below by writing a patch:",
                "input": problem[:5000],
                "output": f"```diff\n{patch[:5000]}\n```",
            }


def parse_jira_csv(root: Path, source_label: str) -> Iterator[Dict]:
    """
    Generic Jira CSV parser. Used for both TAWOS exports and the
    Apache Jira Social Repository. Looks for files with Summary/Description/
    Resolution/Priority/Status columns.
    """
    if not root.exists():
        return
    print(f"    [{source_label}] scanning {root}")
    for csv in list(root.rglob("*.csv")) + list(root.rglob("*.tsv")):
        if csv.stat().st_size < 50_000:
            continue
        try:
            sep = "," if csv.suffix == ".csv" else "\t"
            df = pd.read_csv(csv, sep=sep, low_memory=False, on_bad_lines="skip", nrows=200_000)
        except Exception:
            continue
        cols = {c.lower(): c for c in df.columns}
        c_summary = cols.get("summary") or cols.get("title")
        c_desc    = cols.get("description") or cols.get("body")
        c_priority = cols.get("priority")
        c_resolution = cols.get("resolution") or cols.get("comments")
        c_status  = cols.get("status")
        c_type    = cols.get("issue_type") or cols.get("type")
        if not (c_summary or c_desc):
            continue
        for _, row in df.iterrows():
            title = strip_html(str(row.get(c_summary, "") if c_summary else ""))[:250]
            desc  = strip_html(str(row.get(c_desc, "") if c_desc else ""))[:5000]
            if len(title) + len(desc) < 30:
                continue
            res = strip_html(str(row.get(c_resolution, "") if c_resolution else ""))[:5000]
            if res.lower() in {"nan", "none", "fixed", "duplicate", "invalid", "unresolved"}:
                res = ""
            yield {
                "_source": source_label,
                "_kind": "ticket_labeled" if c_priority else "ticket",
                "title": title,
                "description": desc,
                "resolution": res,
                "priority": normalize_priority(row.get(c_priority) if c_priority else None),
                "category": normalize_category(row.get(c_type) if c_type else None),
                "type": str(row.get(c_type, "issue") if c_type else "issue").lower()[:30],
            }


# ----------------------------------------------------------------------------
#  Main pipeline
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="./raw", help="Raw downloads directory")
    ap.add_argument("--out", default="./processed", help="Output JSONL directory")
    ap.add_argument("--your-data", default=None,
                    help="Path to your final_merged_dataset_cleaned.xlsx")
    args = ap.parse_args()

    raw = Path(args.raw); out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    classification = JsonlWriter(out / "classification.jsonl")
    skills_jsonl   = JsonlWriter(out / "skill_assignment.jsonl")
    resolution     = JsonlWriter(out / "resolution.jsonl")
    instruction    = JsonlWriter(out / "instruction.jsonl")

    source_counts = Counter()
    seen_hashes = set()  # crude dedup

    def emit(obj: Dict):
        kind = obj.get("_kind")
        # Quick dedup based on combined text head
        text_for_dedup = (obj.get("title", "") + obj.get("description", "")
                          + obj.get("instruction", "") + obj.get("output", ""))[:500]
        h = hash(text_for_dedup)
        if h in seen_hashes:
            return
        seen_hashes.add(h)
        source_counts[obj["_source"]] += 1

        full_text = (obj.get("title", "") + " " + obj.get("description", "") + " "
                     + obj.get("instruction", "") + " " + obj.get("input", "")).strip()

        # Classification stream
        if kind in {"ticket_labeled", "ticket_resolved", "ticket"}:
            text = (obj.get("title", "") + "\n\n" + obj.get("description", "")).strip()
            if len(text) >= 30:
                classification.write({
                    "text": text,
                    "labels": {
                        "priority": obj.get("priority", "medium"),
                        "category": obj.get("category", "other"),
                        "type": obj.get("type", "issue"),
                    },
                    "source": obj["_source"],
                })

        # Skill assignment stream — derived from text
        skills = detect_skills(full_text)
        if skills and len(full_text) >= 30:
            skills_jsonl.write({
                "ticket": full_text[:2000],
                "required_skills": skills,
                "source": obj["_source"],
            })

        # Resolution stream — anything with a paired resolution
        if obj.get("resolution") and len(obj["resolution"]) >= 30:
            resolution.write({
                "problem": (obj.get("title", "") + "\n\n" + obj.get("description", "")).strip()[:5000],
                "resolution": obj["resolution"][:5000],
                "tags": obj.get("tags", []),
                "source": obj["_source"],
            })

        # Instruction stream
        if kind == "instruction":
            if obj.get("instruction") and obj.get("output"):
                instruction.write({
                    "instruction": obj["instruction"][:3000],
                    "input": obj.get("input", "")[:3000],
                    "output": obj["output"][:5000],
                    "source": obj["_source"],
                })

    # ---- run all parsers --------------------------------------------------
    print("\n[Module 1] Tickets")
    for r in parse_user_xlsx(args.your_data):
        emit(r)
    for r in parse_gitbugs(raw / "tickets" / "gitbugs"):
        emit(r)

    print("\n[Module 3] Conversational instruction (OASST2)")
    for r in parse_oasst2(raw / "instruction" / "oasst2_ready.jsonl.gz"):
        emit(r)

    print("\n[Module 4] Linux/Bash commands")
    for r in parse_nl2bash(raw / "commands" / "nl2bash_all.cm",
                           raw / "commands" / "nl2bash_all.nl"):
        emit(r)
    for r in parse_nl2sh_alfa(raw / "commands" / "nl2sh_alfa"):
        emit(r)
    tldr_root = raw / "commands" / "tldr-main"
    if tldr_root.exists():
        for r in parse_tldr(tldr_root):
            emit(r)

    print("\n[Module 5] Code bug-fix pairs")
    for r in parse_code_refinement(raw / "code_fixes" / "code_refinement"):
        emit(r)
    for sub in ["swebench_verified", "swebench_lite", "swebench_full"]:
        p = raw / "code_fixes" / sub
        if p.exists():
            for r in parse_swebench(p):
                emit(r)

    print("\n[Module 6] Jira tickets (optional — requires CSV exports)")
    for r in parse_jira_csv(raw / "jira" / "tawos" / "csv_export", "tawos_jira"):
        emit(r)
    for r in parse_jira_csv(raw / "jira" / "jira_social", "apache_jira_social"):
        emit(r)

    # ---- finalize ---------------------------------------------------------
    classification.close(); skills_jsonl.close(); resolution.close(); instruction.close()

    print("\n=== Source counts ===")
    for src, c in source_counts.most_common():
        print(f"   {src:35s}  {c:>10,}")
    print(f"\nTotal unique rows emitted: {sum(source_counts.values()):,}")
    print(f"Output dir: {out.resolve()}")
    print("\nNext: python3 03_verify_outputs.py ./processed")


if __name__ == "__main__":
    main()
