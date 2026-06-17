#!/usr/bin/env bash
# =============================================================================
# EasyMyTicket — Phase B + C deployment script
# Run this from the project root (EasyMyTicket/) with AWS credentials active.
# Prerequisites: aws cli, kubectl, helm all configured and pointing at
#   account 808812816838, region ap-south-1, cluster ticketing-prod-cluster
# =============================================================================
set -euo pipefail

REGION="ap-south-1"
ACCOUNT="808812816838"
CLUSTER="ticketing-prod-cluster"
ECR_REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/ticketing-api"
S3_BUCKET="ticketing-prod-datasets-$ACCOUNT"
NAMESPACE="ticketing"

echo "==========================================================="
echo " EasyMyTicket — Phase B + C Deployment"
echo "==========================================================="

# ── Phase B1: Upload files to S3 ─────────────────────────────────────────────
echo ""
echo "▶ B1: Uploading schema patch and seed script to S3..."
aws s3 cp scripts/db_schema_v3_patch.sql \
    "s3://$S3_BUCKET/build/db_schema_v3_patch.sql" \
    --region "$REGION"
aws s3 cp scripts/seed_technicians.py \
    "s3://$S3_BUCKET/build/seed_technicians.py" \
    --region "$REGION"
echo "  ✅ SQL patch and seed script uploaded"

# ── Phase B1: Run schema v3 patch job ────────────────────────────────────────
echo ""
echo "▶ B1: Deleting old schema job (if exists) and applying schema v3 patch..."
kubectl delete job db-schema-v3 -n "$NAMESPACE" --ignore-not-found=true
kubectl apply -f k8s/db-schema-v3-job.yaml
echo "  ⏳ Waiting for schema job to complete (max 3 min)..."
kubectl wait job/db-schema-v3 -n "$NAMESPACE" \
    --for=condition=complete --timeout=180s
echo "  ✅ Schema v3 patch applied"
kubectl logs -l job-name=db-schema-v3 -n "$NAMESPACE" --tail=5

# ── Phase B2: Build new Docker image ─────────────────────────────────────────
echo ""
echo "▶ B2: Refreshing ECR credentials for Kaniko..."
aws ecr get-login-password --region "$REGION" | \
    kubectl create secret docker-registry ecr-credentials \
        --docker-server="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com" \
        --docker-username=AWS \
        --docker-password="$(aws ecr get-login-password --region $REGION)" \
        -n "$NAMESPACE" \
        --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "▶ B2: Packaging source and uploading to S3..."
# Exclude local dev artifacts
tar --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='*.egg-info' \
    --exclude='.pytest_cache' \
    --exclude='venv' \
    --exclude='.venv' \
    --exclude='node_modules' \
    -czf /tmp/source.tar.gz .
aws s3 cp /tmp/source.tar.gz \
    "s3://$S3_BUCKET/build/source.tar.gz" \
    --region "$REGION"
echo "  ✅ Source uploaded: $(du -h /tmp/source.tar.gz | cut -f1)"

echo ""
echo "▶ B2: Starting Kaniko build job..."
kubectl delete job kaniko-build -n "$NAMESPACE" --ignore-not-found=true
kubectl apply -f k8s/kaniko-build-job.yaml
echo "  ⏳ Waiting for Kaniko build (max 20 min)..."
kubectl wait job/kaniko-build -n "$NAMESPACE" \
    --for=condition=complete --timeout=1200s
echo "  ✅ Image built and pushed to ECR"

# ── Phase B3: Rolling restart ─────────────────────────────────────────────────
echo ""
echo "▶ B3: Rolling restart of API deployment..."
kubectl rollout restart deployment/ticketing-api -n "$NAMESPACE"
kubectl rollout status deployment/ticketing-api -n "$NAMESPACE" --timeout=120s
echo "  ✅ API pods updated"

# ── Phase C1: Fix ElastiCache SG ─────────────────────────────────────────────
echo ""
echo "▶ C1: Looking up ElastiCache security group..."
ELASTICACHE_SG=$(aws elasticache describe-cache-clusters \
    --show-cache-node-info \
    --region "$REGION" \
    --query 'CacheClusters[0].SecurityGroups[0].SecurityGroupId' \
    --output text 2>/dev/null || echo "")

if [ -z "$ELASTICACHE_SG" ] || [ "$ELASTICACHE_SG" = "None" ]; then
    # Try replication groups
    ELASTICACHE_SG=$(aws elasticache describe-replication-groups \
        --region "$REGION" \
        --query 'ReplicationGroups[0].SecurityGroups[0].SecurityGroupId' \
        --output text 2>/dev/null || echo "")
fi

if [ -n "$ELASTICACHE_SG" ] && [ "$ELASTICACHE_SG" != "None" ]; then
    echo "  Found ElastiCache SG: $ELASTICACHE_SG"
    aws ec2 authorize-security-group-ingress \
        --group-id "$ELASTICACHE_SG" \
        --protocol tcp \
        --port 6379 \
        --source-group sg-0a1d764c06cb83028 \
        --region "$REGION" 2>/dev/null \
    && echo "  ✅ Redis SG rule added" \
    || echo "  ⚠️  Rule may already exist — continuing"
else
    echo "  ⚠️  Could not auto-detect ElastiCache SG. Add manually:"
    echo "      aws ec2 authorize-security-group-ingress \\"
    echo "        --group-id <elasticache-sg-id> \\"
    echo "        --protocol tcp --port 6379 \\"
    echo "        --source-group sg-0a1d764c06cb83028 --region $REGION"
fi

# ── Phase C2: Deploy worker pod ───────────────────────────────────────────────
echo ""
echo "▶ C2: Deploying notification worker..."
kubectl apply -f k8s/worker-deployment.yaml
echo "  ✅ Worker deployment applied"

# ── Phase C3: Seed technicians ────────────────────────────────────────────────
echo ""
echo "▶ C3: Seeding technicians..."
kubectl delete job seed-technicians -n "$NAMESPACE" --ignore-not-found=true
kubectl apply -f k8s/seed-technicians-job.yaml
echo "  ⏳ Waiting for seed job (max 2 min)..."
kubectl wait job/seed-technicians -n "$NAMESPACE" \
    --for=condition=complete --timeout=120s
echo "  ✅ Technicians seeded"
kubectl logs -l job-name=seed-technicians -n "$NAMESPACE" --tail=3

# ── Phase C4: ALB / Ingress ───────────────────────────────────────────────────
echo ""
echo "▶ C4: Checking if AWS Load Balancer Controller is installed..."
if ! helm status aws-load-balancer-controller -n kube-system &>/dev/null; then
    echo "  Installing AWS Load Balancer Controller..."
    helm repo add eks https://aws.github.io/eks-charts 2>/dev/null || true
    helm repo update eks
    helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
        -n kube-system \
        --set clusterName="$CLUSTER" \
        --set serviceAccount.create=false \
        --set serviceAccount.name=ticketing-sa \
        --wait --timeout=5m
    echo "  ✅ ALB Controller installed"
else
    echo "  ✅ ALB Controller already installed"
fi

echo ""
echo "▶ C4: Getting public subnet IDs..."
SUBNETS=$(aws ec2 describe-subnets \
    --filters "Name=tag:kubernetes.io/role/elb,Values=1" \
    --region "$REGION" \
    --query 'Subnets[].SubnetId' \
    --output text | tr '\t' ',')

echo "  Found subnets: $SUBNETS"

if [ -n "$SUBNETS" ]; then
    # Update ingress.yaml with real subnet IDs (inline sed)
    sed -i "s|alb.ingress.kubernetes.io/subnets:.*|alb.ingress.kubernetes.io/subnets: $SUBNETS|" \
        k8s/ingress.yaml
    echo "  ✅ ingress.yaml updated with subnet IDs"
    kubectl apply -f k8s/ingress.yaml
    echo "  ⏳ Waiting ~60s for ALB to provision..."
    sleep 60
    echo ""
    echo "▶ ALB DNS Name:"
    kubectl get ingress -n "$NAMESPACE" \
        -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}' 2>/dev/null \
    && echo "" || echo "  (ALB still provisioning — check again in a few minutes)"
else
    echo "  ⚠️  No public subnets found with tag kubernetes.io/role/elb=1"
    echo "      Tag your public subnets and re-run, or apply ingress.yaml manually"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "==========================================================="
echo " Deployment complete! Next steps:"
echo "  • C5: Add GitHub secrets (see plan section C5)"
echo "  • D:  Run E2E smoke tests against the ALB DNS above"
echo "==========================================================="
