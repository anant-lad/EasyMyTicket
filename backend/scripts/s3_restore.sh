#!/bin/bash
# Script to fetch the latest encrypted backup from S3, decrypt, and restore

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
TEMP_DIR="/tmp/db_restores"
S3_PATH="s3://${S3_BUCKET_NAME}/backups/"

echo "🔄 Starting S3 Database Restore..."

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

# 3. Find latest backup in S3
echo "🔍 Searching for latest backup in ${S3_PATH}..."
LATEST_FILE=$(aws s3api list-objects-v2 --bucket "$S3_BUCKET_NAME" --prefix "backups/" --query 'sort_by(Contents, &LastModified)[-1].Key' --output text)

if [ "$LATEST_FILE" == "None" ] || [ -z "$LATEST_FILE" ]; then
    echo "⚠ No backups found in S3 bucket."
    exit 0
fi

echo "📂 Latest backup found: ${LATEST_FILE}"
ENC_FILE="${TEMP_DIR}/$(basename "$LATEST_FILE")"
RAW_FILE="${ENC_FILE%.enc}"

# 4. Download
echo "📥 Downloading backup from S3..."
if ! aws s3 cp "s3://${S3_BUCKET_NAME}/${LATEST_FILE}" "$ENC_FILE"; then
    echo "❌ Error: S3 download failed!"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# 5. Decrypt
echo "🔓 Decrypting backup..."
if ! openssl enc -aes-256-cbc -d -salt -pbkdf2 -iter 100000 -pass "pass:${BACKUP_ENCRYPTION_KEY}" -in "$ENC_FILE" -out "$RAW_FILE"; then
    echo "❌ Error: Decryption failed! (Is your BACKUP_ENCRYPTION_KEY correct?)"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# 6. Restore to Database
echo "🚀 Importing data into database..."
if ! cat "$RAW_FILE" | docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" "$DB_NAME"; then
    echo "❌ Error: Database restoration failed!"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# 7. Cleanup
rm -rf "$TEMP_DIR"

echo "✅ Database successfully restored from S3!"
