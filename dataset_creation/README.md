# End-to-End Real Dataset Pipeline — Commercial-Safe Edition

This pipeline downloads ~6 GB of **real, human-generated, commercially-licensed** data and processes it into four training-ready JSONL files. The resulting model can be released under **your own commercial license** without share-alike obligations.

## What's in this pipeline

```
DATASETS.md                     ← Dataset catalog, licenses, capability map
ATTRIBUTION.md                  ← Required attribution template for your model card
01_download_all.sh              ← Downloads everything into ./raw/
02_build_unified_dataset.py     ← Processes raw → ./processed/*.jsonl
03_verify_outputs.py            ← Sanity-checks the processed files
README.md                       ← This file
```

## What changed from the open-source version

This pipeline **removes** three datasets that block commercial release:

| Removed | License | Why |
|---|---|---|
| Tobi-Bueck customer support tickets | CC-BY-NC-4.0 | Non-commercial only |
| Stack Exchange dumps (all 6 sites) | CC-BY-SA 4.0 | Share-alike forces your model to be CC-BY-SA |
| Databricks Dolly 15K | CC-BY-SA 3.0 | Same share-alike issue |

**Net data loss**: ~10 GB of downloads, ~2.7M Q&A pairs. Most affected: resolution-generation training data.

**Replacement strategy**:
- Replaced classification labels with GitBugs (150K real bug reports across 9 projects).
- Replaced Stack Exchange Q&A with a **RAG-first architecture** at inference time (your own ticket history is the retrieval corpus).
- Replaced Dolly's instruction data with OASST2 alone (Apache 2.0).

The trade-off is documented honestly in `DATASETS.md`. The model will be slightly weaker at *generic* technical resolutions and stronger at *your domain-specific* resolutions when paired with RAG.

## Prerequisites

On your g5.12xlarge (Ubuntu 22.04 / 24.04):

```bash
sudo apt-get update
sudo apt-get install -y curl git p7zip-full python3 python3-pip unzip
pip3 install --user datasets huggingface_hub pandas pyarrow openpyxl
```

You'll need **~30 GB free disk** during processing.

## Step 1 — Download all raw datasets (~15–30 min, mostly bandwidth-bound)

```bash
chmod +x 01_download_all.sh
./01_download_all.sh
```

Populates `./raw/`:

```
raw/
├── tickets/gitbugs/                       # 150K real bug reports
├── skills/onet/                           # O*NET skills taxonomy
├── instruction/oasst2_ready.jsonl.gz      # OpenAssistant
├── commands/
│   ├── nl2bash_all.cm + nl2bash_all.nl    # NL2Bash
│   ├── nl2sh_alfa/                        # NL2SH-ALFA
│   └── tldr-main/                         # TLDR pages
├── code_fixes/
│   ├── code_refinement/                   # CodeXGLUE Java
│   ├── swebench_verified/                 # SWE-bench
│   └── swebench_lite/
└── jira/
    ├── tawos/                             # 508K Jira (MySQL dump)
    └── jira_social/                       # Apache Jira Social
```

Idempotent — already-downloaded files are skipped on re-run.

### Optional: Extract TAWOS Jira data

TAWOS ships as a MySQL dump. To use it, extract to CSV using Docker:

```bash
cd raw/jira
docker run --rm -d -e MYSQL_ROOT_PASSWORD=tmp --name tawos-mysql \
  -v "$PWD/tawos":/data mariadb:10
sleep 15  # wait for MySQL to start

docker exec -i tawos-mysql mysql -uroot -ptmp -e "CREATE DATABASE tawos;"
docker exec -i tawos-mysql sh -c \
  'mysql -uroot -ptmp tawos < /data/MySQL_Dump/TAWOS.sql'

mkdir -p tawos/csv_export
docker exec tawos-mysql mysqldump -uroot -ptmp -T /tmp tawos issues
docker cp tawos-mysql:/tmp/issues.txt tawos/csv_export/issues.csv
docker stop tawos-mysql
```

If you skip this, the pipeline still works — it just produces fewer Jira-style classification rows.

## Step 2 — Build unified training JSONL files

```bash
python3 02_build_unified_dataset.py \
    --raw       ./raw \
    --out       ./processed \
    --your-data /path/to/final_merged_dataset_cleaned.xlsx
```

Runtime: 15–45 min depending on CPU.

Produces:

| File | Schema | Use for |
|---|---|---|
| `classification.jsonl` | `{text, labels:{priority, category, type}, source}` | Fine-tuning the classification head |
| `skill_assignment.jsonl` | `{ticket, required_skills:[...], source}` | Fine-tuning the smart-assignment agent |
| `resolution.jsonl` | `{problem, resolution, tags, source}` | RAG corpus + supervised resolution training |
| `instruction.jsonl` | `{instruction, input, output, source}` | Fine-tuning command/code/debug behavior |

Expected row counts (commercial-safe edition):

```
classification.jsonl   ~180,000 rows
skill_assignment.jsonl ~250,000 rows
resolution.jsonl       ~50,000 rows    ← weaker than open-source variant; lean on RAG
instruction.jsonl      ~220,000 rows
```

## Step 3 — Verify outputs

```bash
python3 03_verify_outputs.py ./processed
```

## Capability assessment vs. your goals

| Goal | Coverage | Notes |
|---|---|---|
| Ticket classification | ✓ Strong | 180K labeled examples is plenty for 7B + LoRA |
| Skill-based technician assignment | ✓ Strong | Rule-based + 250K text→skill examples |
| Generate Linux/bash commands ("bluetooth not working") | ✓ Strong | NL2Bash + NL2SH-ALFA + TLDR = 90K real pairs |
| Generate code / debug Linux issues | ✓ Strong | SWE-bench + CodeXGLUE = 120K real pairs |
| Repeated/automation tasks | ◑ Adequate | Covered by NL2SH-ALFA + your tickets |
| Project / Jira tickets | ✓ Strong | TAWOS + Apache Jira Social = 1.2M tickets |
| Hardware tickets (Bluetooth, drivers, GPU) | ◐ Weaker | Lost SE's 40K hardware Q&A — supplement with RAG over your own history |
| ITSM / general support tickets | ◐ Weaker | Lost SE + Tobi-Bueck — supplement with RAG and domain-expert annotation |
| Generic technical Q&A | ◐ Weaker | OASST2 alone — model learns conversational style but less breadth |

## Recommended training recipe

**Base model**: `Qwen/Qwen2.5-Coder-7B-Instruct` (Apache 2.0 — commercial-safe)

Train **one base model with three LoRA adapters**:

1. **Adapter A — Classifier**
   LoRA on `classification.jsonl`, 3 epochs, ~3 hrs
   Predicts `{priority, category, type}` for incoming tickets.

2. **Adapter B — Skill router**
   LoRA on `skill_assignment.jsonl`, 2 epochs, ~2 hrs
   Multi-label classification for `{required_skills}` → routes to technician queue.

3. **Adapter C — Resolution writer**
   LoRA on `resolution.jsonl` + `instruction.jsonl` mixed 1:1, 3 epochs, ~12 hrs
   Generates resolution steps, commands, code fixes given problem + retrieved context.

**RAG index**: Embed all of `resolution.jsonl` AND your existing 28K resolved real tickets with `BAAI/bge-large-en-v1.5` (MIT licensed) into pgvector. At inference time, retrieve top-5 similar resolved tickets and feed them as context to Adapter C.

**This is critical for commercial release**: with reduced training data, retrieval-augmented inference is what makes the model genuinely useful. The architecture you drew on your project poster already shows pgvector — lean into it harder than you would with the open-source data version.

## Inference flow

```
new ticket comes in
    ↓
Adapter A classifies → {priority, category, type}
    ↓
Adapter B predicts → {required_skills} → routes to technician queue
    ↓
pgvector retrieves top-5 similar resolved tickets
    ↓
Adapter C generates resolution / commands / code, conditioned on retrieval
    ↓
Notification agent emails the technician
```

## Commercial release checklist

Before you ship, complete this checklist:

- [ ] Run `./01_download_all.sh` and `python3 02_build_unified_dataset.py`
- [ ] Run `python3 03_verify_outputs.py` — confirm row counts and label distributions
- [ ] Train your three LoRA adapters (~17 hours total on g5.12xlarge)
- [ ] Build evaluation set: 300+ hand-curated tickets with gold-standard resolutions
- [ ] Benchmark the model on the eval set
- [ ] Set up pgvector RAG over your own resolved tickets
- [ ] **Copy the attribution block from `ATTRIBUTION.md` into your model card**
- [ ] Choose your model's commercial license (Apache 2.0 is a popular permissive choice; or fully proprietary EULA)
- [ ] Publish your model — either openly on HuggingFace or as a hosted API behind your product

## What this pipeline does NOT include

- **Training scripts** — separate task; ask if you want LoRA SFT scripts using `axolotl` or `trl`
- **Synthetic data generation** — explicitly excluded per your instructions
- **PII scrubbing for your own MSP data** — your existing Excel already has redactions, but if you're worried about new data, add a PII pass before training
- **Stack Exchange data** — see `DATASETS.md` for why this is intentionally excluded; if you want it back, you must either (a) license it commercially from Stack Overflow Inc., or (b) accept CC-BY-SA on your model

## Troubleshooting

**`huggingface_hub` 401/403 errors**: Some datasets gate behind license acceptance. Run `huggingface-cli login` and visit the dataset's page in a browser to click "Agree".

**OOM during step 2**: The dedup `set` in `emit()` grows. If you run out of RAM, comment out the `seen_hashes` lines — you'll get ~5% duplicates but it'll fit anywhere.

**TAWOS Docker setup fails**: It's optional. The pipeline runs fine without TAWOS — you'll just get a smaller Jira contribution. The Apache Jira Social Repository alone gives you ~700K Jira tickets.

**GitBugs CSV files won't parse**: Some projects in GitBugs use non-standard column names. The parser handles common aliases; check the warnings emitted during step 2 for skipped CSVs and add aliases to the `ALIAS` dict in `parse_gitbugs()` if needed.

End-to-end runtime on a g5.12xlarge: **~1–2 hours** including downloads.
