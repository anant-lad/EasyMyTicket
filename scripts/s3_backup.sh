#!/bin/bash
# Script to backup PostgreSQL, encrypt with AES-256, and upload to S3

# Load environment variables
if [ -f .env ]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ ! "$line" =~ ^# ]] && [[ "$line" =~ = ]]; then
            key=$(echo "$line" | cut -d'=' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            value=$(echo "$line" | cut -d'=' -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//")
            export "$key"="$value"
        fi
    done < .env
fi

# Constants
DB_CONTAINER="Autotask"
DB_NAME="tickets_db"
DB_USER="admin"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
TEMP_DIR="/tmp/db_backups"
RAW_FILE="${TEMP_DIR}/backup_${TIMESTAMP}.sql"
ENC_FILE="${RAW_FILE}.enc"
S3_PATH="s3://${S3_BUCKET_NAME}/backups/"
MAX_BACKUPS=10

echo "🔄 Starting S3 Database Backup..."

# 1. Validation
if [ -z "$S3_BUCKET_NAME" ] || [ -z "$BACKUP_ENCRYPTION_KEY" ]; then
    echo "❌ Error: S3_BUCKET_NAME or BACKUP_ENCRYPTION_KEY is not set in .env"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo "❌ Error: AWS CLI is not installed."
    exit 1
fi

# 2. Preparation
mkdir -p "$TEMP_DIR"

# 3. Dump Database
echo "📦 Dumping database..."
if ! docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" > "$RAW_FILE"; then
    echo "❌ Error: Database dump failed!"
    rm -f "$RAW_FILE"
    exit 1
fi

# 4. Encrypt
echo "🔐 Encrypting backup with AES-256..."
if ! openssl enc -aes-256-cbc -salt -pbkdf2 -iter 100000 -pass "pass:${BACKUP_ENCRYPTION_KEY}" -in "$RAW_FILE" -out "$ENC_FILE"; then
    echo "❌ Error: Encryption failed!"
    rm -f "$RAW_FILE" "$ENC_FILE"
    exit 1
fi

# 5. Upload to S3
echo "🚀 Uploading to S3: ${S3_PATH}"
if ! aws s3 cp "$ENC_FILE" "$S3_PATH"; then
    echo "❌ Error: S3 Upload failed!"
    rm -f "$RAW_FILE" "$ENC_FILE"
    exit 1
fi

# 6. Maintenance (Rotate old backups)
echo "🧹 Cleaning up old backups from S3 (Keeping latest ${MAX_BACKUPS})..."
BACKUP_LIST=$(aws s3 ls "$S3_PATH" | sort -r | awk '{print $4}')
COUNT=0
for FILE in $BACKUP_LIST; do
    COUNT=$((COUNT + 1))
    if [ $COUNT -gt $MAX_BACKUPS ]; then
        echo "🗑 Deleting old backup: $FILE"
        aws s3 rm "${S3_PATH}${FILE}"
    fi
done

# 7. Local Cleanup
rm -f "$RAW_FILE" "$ENC_FILE"

echo "✅ Backup successfully encrypted and uploaded to S3!"
