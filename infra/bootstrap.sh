#!/usr/bin/env bash
# Run ONCE before `terraform init` to create the S3 state bucket and DynamoDB lock table.
# Usage: AWS_PROFILE=default bash infra/bootstrap.sh

set -euo pipefail

REGION="ap-south-1"
ACCOUNT_ID="808812816838"
BUCKET="ticketing-prod-tf-state-${ACCOUNT_ID}"
TABLE="ticketing-terraform-locks"

echo "==> Creating Terraform state bucket: $BUCKET"
aws s3 mb "s3://${BUCKET}" --region "$REGION" 2>/dev/null || echo "Bucket already exists"

aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{
    "Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]
  }'

aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "==> Creating DynamoDB lock table: $TABLE"
aws dynamodb create-table \
  --table-name "$TABLE" \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "$REGION" 2>/dev/null || echo "Table already exists"

echo ""
echo "✅  Bootstrap complete. Now run:"
echo "    cd infra/terraform && terraform init && terraform plan"
