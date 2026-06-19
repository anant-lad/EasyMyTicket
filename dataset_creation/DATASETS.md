# Commercial-Safe Real Dataset Catalog

**This is the version for proprietary commercial release of your fine-tuned model.**

Every dataset listed below has a license that explicitly permits:
- training proprietary models on it,
- releasing the trained model under your own commercial license,
- without share-alike obligations on the model weights.

Where attribution is required (e.g. CC BY 4.0), the requirement is satisfied by listing the source in your model card / NOTICE file. See `ATTRIBUTION.md` for the template.

---

## Module 1 — Ticket Classification

### 1.1 GitBugs ★ Primary
- **What it is**: 150,000+ real bug reports from 9 open-source projects (Cassandra, Firefox, Hadoop, HBase, Mozilla Core, VS Code, Seamonkey, Spark, Thunderbird) aggregated from GitHub Issues, JIRA, and Bugzilla. Standardized fields: `Summary`, `Description`, `Status`, `Priority`, `Resolution`.
- **Direct link**: <https://github.com/av9ash/gitbugs>
- **Paper**: <https://arxiv.org/abs/2504.09651>
- **License**: Per-project — Apache 2.0 (Cassandra, Hadoop, HBase, Spark), MPL 2.0 (Firefox, Mozilla Core, Thunderbird, Seamonkey), MIT (VS Code). **All commercial-safe.**
- **Size**: ~1 GB
- **Source type**: 100% real (scraped from production bug trackers)

### 1.2 Your existing dataset (`final_merged_dataset_cleaned.xlsx`)
- 162,971 rows. Use only the **62,971 Real rows** (drop the 100K synthetic). You own this data.

---

## Module 2 — Technician Skill Assignment

### 2.1 O*NET Computer Occupations Skills Taxonomy
- **What it is**: U.S. Department of Labor's database of occupational skills. Source of truth for skill labels: Network Admin, DBA, Sysadmin, Helpdesk, DevOps, Security Analyst, etc.
- **Direct link**: <https://www.onetcenter.org/dl_files/database/db_29_0_text.zip>
- **License**: **Public domain** (U.S. government)
- **Size**: 70 MB

Skill labels are derived from text via the rule-based detector in `02_build_unified_dataset.py`. No external skill→ticket dataset is needed.

---

## Module 3 — Conversational Instruction Data

### 3.1 OpenAssistant OASST2 ★
- **What it is**: 128,575 real human-written assistant conversations from 13,500+ volunteer contributors. Filtered to technical conversations during processing.
- **Direct link**: <https://huggingface.co/datasets/OpenAssistant/oasst2/resolve/main/2023-11-05_oasst2_ready.messages.jsonl.gz>
- **License**: **Apache 2.0** — fully commercial-safe, no share-alike
- **Size**: 54 MB compressed
- **Source type**: 100% real (human crowdsourced)

---

## Module 4 — Linux/Bash Command Generation

### 4.1 NL2Bash (Tellina) ★
- **What it is**: 9,305 expert-curated (English description → Bash command) pairs.
- **Direct links**:
  - <https://raw.githubusercontent.com/TellinaTool/nl2bash/master/data/bash/all.cm>
  - <https://raw.githubusercontent.com/TellinaTool/nl2bash/master/data/bash/all.nl>
- **License**: **MIT**
- **Size**: 2 MB
- **Paper**: <https://arxiv.org/abs/1802.08979>

### 4.2 NL2SH-ALFA
- **What it is**: ~70K NL→shell pairs covering more utilities than NL2Bash.
- **HF page**: <https://huggingface.co/datasets/westenfelder/NL2SH-ALFA>
- **License**: **MIT**
- **Size**: 15 MB
- **Paper**: <https://arxiv.org/abs/2502.06129>

### 4.3 TLDR-pages
- **What it is**: 12,000+ community-maintained example commands for ~3,000 CLI tools across Linux, macOS, Windows, Android.
- **Direct link**: <https://github.com/tldr-pages/tldr/archive/refs/heads/main.zip>
- **License**: **CC BY 4.0** — commercial-safe with attribution (no share-alike)
- **Size**: 50 MB
- **Attribution required**: Yes — see `ATTRIBUTION.md`

---

## Module 5 — Real Code Bug-Fix Pairs

### 5.1 SWE-bench (Verified) ★
- **What it is**: Real GitHub issues + the actual PR patch that fixed them, from 12 popular Python repos.
- **HF dataset**: `SWE-bench/SWE-bench_Verified` (500 verified) and `SWE-bench/SWE-bench` (full)
- **License**: **MIT**
- **Source type**: 100% real (every patch is a real merged PR)

### 5.2 CodeXGLUE Code Refinement (Java bug fixes)
- **What it is**: 122,000 (buggy Java function → fixed Java function) pairs mined from real GitHub commit histories.
- **HF dataset**: `google/code_x_glue_cc_code_refinement`
- **License**: **C-UDA** (Computational Use of Data Agreement) — permissive, commercial use OK
- **Size**: 50 MB

---

## Module 6 — Real JIRA Project Tickets

### 6.1 TAWOS — The Agile Open-source Software Dataset
- **What it is**: 508,963 real Jira issues from 44 projects across 13 ecosystems (Apache, Atlassian, Spring, Hyperledger, MongoDB, Moodle, Sonatype, etc.). Includes story points, status transitions, components, sprints.
- **Direct link**: <https://github.com/SOLAR-group/TAWOS>
- **License**: Original Jira content is governed by per-project license. **Apache projects = Apache 2.0**, the dominant share. For projects with stricter licenses (MongoDB SSPL etc.), exclude them via the `--include-projects` filter in the parser.
- **Size**: ~2 GB
- **Caveat**: Distributed as a MySQL dump — see Step 2 in `README.md` for the Docker-based extraction.

### 6.2 Apache Jira Social Repository
- **What it is**: 700K issue reports + 2M comments from Apache, Spring, JBoss, CodeHaus.
- **Direct link**: <https://github.com/marcoortu/jira-social-repository>
- **License**: All four ecosystems are governed by Apache 2.0 (Apache, Spring, JBoss historic) or similarly permissive licenses. Commercial-safe.
- **Size**: ~500 MB

---

## License Summary — every dataset is commercial-safe

| Dataset | License | Attribution required? | Share-alike? |
|---|---|---|---|
| GitBugs (per-project) | Apache 2.0 / MPL 2.0 / MIT | ✓ in NOTICE | ❌ No |
| O*NET | Public domain | Recommended | ❌ No |
| OASST2 | Apache 2.0 | ✓ LICENSE in distribution | ❌ No |
| NL2Bash | MIT | ✓ in NOTICE | ❌ No |
| NL2SH-ALFA | MIT | ✓ in NOTICE | ❌ No |
| TLDR-pages | CC BY 4.0 | ✓ in model card | ❌ No |
| SWE-bench | MIT | ✓ in NOTICE | ❌ No |
| CodeXGLUE | C-UDA | ✓ recommended | ❌ No |
| TAWOS Jira | per-project (mostly Apache 2.0) | ✓ in NOTICE | ❌ No |
| Apache Jira Social | Apache 2.0 | ✓ in NOTICE | ❌ No |
| Your MSP data | Yours | — | — |

You can ship the trained model under your own commercial license. Just include the attribution file (template in `ATTRIBUTION.md`) with your model release.

---

## Capability Coverage Map (Commercial-Safe Edition)

| Capability | Sources | Volume |
|---|---|---|
| Ticket classification | GitBugs + your real data | ~180K labeled |
| Technician skill assignment | Rule-based on all text + O*NET taxonomy | ~250K skill-tagged |
| Real Q&A / problem→resolution | Your real tickets + GitBugs (with resolutions) | ~50K pairs |
| Linux/Bash commands | NL2Bash + NL2SH-ALFA + TLDR | ~90K NL→cmd pairs |
| Code writing / debugging | SWE-bench + CodeXGLUE | ~120K bug-fix pairs |
| Conversational technical instruction | OASST2 (filtered) | ~15K pairs |
| Project / Jira tickets | TAWOS + Apache Jira Social | ~1.2M (most without resolutions) |

**Total trainable rows after dedup and filtering: ~700K–800K** (down from ~3.5M in the open-source variant).

---

## What was removed and why

These three sources were dropped because of license incompatibility with proprietary commercial release:

| Dataset | License | Problem |
|---|---|---|
| Tobi-Bueck customer support tickets | CC-BY-NC-4.0 | Non-commercial only |
| Stack Exchange dumps (all 6 sites) | CC-BY-SA 4.0 | Share-alike forces your model to also be CC-BY-SA |
| Databricks Dolly 15K | CC-BY-SA 3.0 | Share-alike same issue |

**Combined data loss**: ~10 GB downloads, ~2.7M rows of real Q&A pairs.

---

## Honest assessment of the trade-off

Without Stack Exchange, your **resolution-generation capability is the most affected**. The remaining real Q→A pairs (~50K) come mostly from your MSP tickets and GitBugs bug reports, which are narrower in scope than the millions of Q&A from Server Fault / Super User / Ask Ubuntu.

To compensate, lean harder on three things:

1. **RAG over your own ticket corpus.** Embed your 28K resolved real tickets with `BAAI/bge-large-en-v1.5` and retrieve at runtime. This is more effective than memorizing answers in weights.
2. **Domain-expert annotation.** Have your team write 1,000–3,000 high-quality, hand-crafted (problem → resolution) pairs specific to *your customers' actual issues*. This dwarfs the value of generic Stack Exchange data for your specific deployment.
3. **Optional: license SE data commercially.** Stack Exchange offers commercial API/data access via their enterprise team. If your business case justifies it, this gets you the missing 2.7M rows back legally.

Other capabilities (classification, command generation, code debugging) are minimally affected — the commercial-safe sources cover them well.
