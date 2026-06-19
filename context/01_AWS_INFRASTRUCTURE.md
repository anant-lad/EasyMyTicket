# EasyMyTicket — AWS Infrastructure Architecture

**Account:** 808812816838 | **Region:** ap-south-1 (Mumbai) | **IaC:** Terraform ≥ 1.6

---

## High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              INTERNET                                                │
│                                                                                      │
│   [Users / Browsers]    [Technician Dashboard]    [Desktop Agents (Win/Mac/Linux)]   │
└──────────────┬──────────────────┬──────────────────────────────┬────────────────────┘
               │ HTTPS            │ HTTPS                        │ WSS (WebSocket)
               ▼                  ▼                              ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                    AWS VPC  10.0.0.0/16  (ap-south-1)                               │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                       PUBLIC SUBNETS                                          │   │
│  │  10.0.1.0/24 (ap-south-1a)    10.0.2.0/24 (ap-south-1b)                     │   │
│  │                                                                               │   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐ │   │
│  │  │          AWS Application Load Balancer (ALB)                             │ │   │
│  │  │          • Internet-facing, HTTPS:443 + HTTP:80                          │ │   │
│  │  │          • Routes to EKS pods on port 8000                               │ │   │
│  │  │          • Managed by AWS Load Balancer Controller (Helm chart)           │ │   │
│  │  └─────────────────────────────────────────────────────────────────────────┘ │   │
│  │                                                                               │   │
│  │  ┌──────────────────┐  ┌──────────────────┐                                  │   │
│  │  │   NAT Gateway 1  │  │   NAT Gateway 2  │  (one per AZ for HA)             │   │
│  │  │   (EIP)          │  │   (EIP)          │  Private → Internet egress       │   │
│  │  └──────────────────┘  └──────────────────┘                                  │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                   │                                                  │
│                                   │ (routes to EKS pods)                            │
│                                   ▼                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                       PRIVATE SUBNETS                                         │   │
│  │  10.0.3.0/24 (ap-south-1a)    10.0.4.0/24 (ap-south-1b)                     │   │
│  │                                                                               │   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐ │   │
│  │  │                  EKS CLUSTER  (K8s 1.32)                                 │ │   │
│  │  │                                                                           │ │   │
│  │  │  ┌─────────────────────────────┐  ┌───────────────────────────────────┐  │ │   │
│  │  │  │   API NODE GROUP            │  │   WORKER NODE GROUP               │  │ │   │
│  │  │  │   t3.medium (2-6 nodes)     │  │   t3.large (1-4 nodes)            │  │ │   │
│  │  │  │                             │  │                                   │  │ │   │
│  │  │  │  ┌───────────────────────┐  │  │  ┌─────────────────────────────┐ │  │ │   │
│  │  │  │  │  ticketing-api Pod ×2  │  │  │  │  ticketing-worker Pod ×1   │ │  │ │   │
│  │  │  │  │  FastAPI / Uvicorn     │  │  │  │  SQS consumer              │ │  │ │   │
│  │  │  │  │  Port 8000             │  │  │  │  Email dispatcher          │ │  │ │   │
│  │  │  │  │  CPU: 256m–1000m      │  │  │  │  (taint: embedding)        │ │  │ │   │
│  │  │  │  │  RAM: 1Gi–2Gi         │  │  │  └─────────────────────────────┘ │  │ │   │
│  │  │  │  └───────────────────────┘  │  └───────────────────────────────────┘  │ │   │
│  │  │  │                             │                                           │ │   │
│  │  │  │  HPA: 2–6 replicas          │                                           │ │   │
│  │  │  │  Metric: CPU > 70%          │                                           │ │   │
│  │  │  └─────────────────────────────┘                                           │ │   │
│  │  │                                                                             │ │   │
│  │  │  EKS Add-ons: CoreDNS, kube-proxy, vpc-cni, aws-ebs-csi-driver            │ │   │
│  │  │  Helm: metrics-server, aws-load-balancer-controller                         │ │   │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │   │
│  │                                                                               │   │
│  │  ┌────────────────────┐  ┌────────────────────┐  ┌─────────────────────────┐ │   │
│  │  │  RDS PostgreSQL 16  │  │  ElastiCache Redis  │  │  SQS Queues             │ │   │
│  │  │  db.t3.medium       │  │  cache.t3.micro     │  │                         │ │   │
│  │  │  20GB gp3           │  │  7.1 + TLS          │  │  notification-queue     │ │   │
│  │  │  Encrypted          │  │  LRU eviction       │  │  llm-queue              │ │   │
│  │  │  7-day backups      │  │  1h TTL (vectors)   │  │  + DLQs (14-day)       │ │   │
│  │  │  Multi-AZ ready     │  │  24h TTL (picklist) │  │  Long-poll (20s)        │ │   │
│  │  └────────────────────┘  └────────────────────┘  └─────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                    SUPPORTING SERVICES                                         │   │
│  │                                                                               │   │
│  │  ┌──────────────┐  ┌──────────────────────┐  ┌───────────────────────────┐  │   │
│  │  │  ECR (3 repos) │  │  Secrets Manager      │  │  CloudWatch + Alarms      │  │   │
│  │  │  ticketing-api │  │  groq-api-key         │  │  EKS metrics              │  │   │
│  │  │  worker       │  │  email-credentials    │  │  RDS metrics              │  │   │
│  │  │  agent-build  │  │  api-keys             │  │  SQS queue depth          │  │   │
│  │  └──────────────┘  │  redis-credentials    │  │  Application logs         │  │   │
│  │                     └──────────────────────┘  └───────────────────────────┘  │   │
│  │                                                                               │   │
│  │  ┌──────────────────────────────────────────────────────────────────────┐    │   │
│  │  │  S3 Buckets                                                            │    │   │
│  │  │  ticketing-prod-tf-state-808812816838  (Terraform state, versioned)   │    │   │
│  │  │  ticketing-prod-assets-808812816838    (Static files, backups)        │    │   │
│  │  │  DynamoDB: ticketing-terraform-locks   (State locking)                │    │   │
│  │  └──────────────────────────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Network Topology

```
Internet
    │
    ▼
Internet Gateway (IGW)
    │
    ├── Public Subnet ap-south-1a (10.0.1.0/24)
    │       └── ALB (internet-facing)
    │       └── NAT GW 1 (EIP)
    │
    ├── Public Subnet ap-south-1b (10.0.2.0/24)
    │       └── NAT GW 2 (EIP)
    │
    ├── Private Subnet ap-south-1a (10.0.3.0/24)
    │       ├── EKS Nodes (API + Worker)
    │       ├── RDS Primary
    │       └── ElastiCache Node
    │
    └── Private Subnet ap-south-1b (10.0.4.0/24)
            ├── EKS Nodes (failover)
            └── RDS standby-ready

Security Group Rules:
  ALB SG       → port 80/443 from 0.0.0.0/0
  EKS Nodes SG ← port 8000 from ALB SG only
  RDS SG       ← port 5432 from EKS Nodes SG only
  Redis SG     ← port 6379 from EKS Nodes SG only
```

---

## IAM & IRSA (IAM Roles for Service Accounts)

```
EKS OIDC Provider
        │
        ├── ticketing-pod-role  (IRSA — main application)
        │     Permissions:
        │     ├── SQS: SendMessage, ReceiveMessage, DeleteMessage
        │     ├── Secrets Manager: GetSecretValue
        │     ├── ECR: GetAuthorizationToken, BatchGetImage
        │     ├── S3: PutObject, GetObject (assets bucket)
        │     └── CloudWatch: PutMetricData, CreateLogStream
        │
        ├── ebs-csi-role        (IRSA — EBS volume provisioning)
        │     Permissions: AmazonEBSCSIDriverPolicy
        │
        └── alb-controller-role (IRSA — ALB ingress management)
              Permissions: alb_controller_policy.json (full ALB control)
```

---

## CI/CD Pipeline

```
Developer pushes to GitHub
        │
        ▼
GitHub Actions: .github/workflows/
        │
        ├── On Pull Request:
        │     └── Run tests (pytest)
        │
        └── On merge to main:
              ├── Build Docker image
              ├── Push to ECR (ticketing-api:latest)
              └── kubectl apply -f k8s/  →  EKS Rolling Update
```

---

## Kubernetes Resource Summary

| Resource | Kind | Details |
|---|---|---|
| `ticketing` | Namespace | Isolated namespace for all resources |
| `ticketing-api` | Deployment | 2 replicas, rolling update, node: api |
| `ticketing-worker` | Deployment | 1 replica, node: worker (embedding taint) |
| `ticketing-service` | Service | ClusterIP on port 8000 |
| `ticketing-ingress` | Ingress | ALB controller, HTTPS termination |
| `ticketing-hpa` | HPA | 2–6 replicas, CPU threshold 70% |
| `ticketing-config` | ConfigMap | RDS endpoint, Redis host, SQS URLs |
| `ticketing-secrets` | Secret | API keys, DB password (from Secrets Manager) |
| `ticketing-sa` | ServiceAccount | IRSA annotation for pod IAM role |

---

## Terraform State Management

```
S3 Bucket: ticketing-prod-tf-state-808812816838
Key:       prod/terraform.tfstate
Encrypt:   AES-256 (SSE-S3)
Versioned: Yes

DynamoDB: ticketing-terraform-locks
  ← prevents concurrent terraform apply runs
```

---

## AWS Services Cost Profile (ap-south-1)

| Service | Spec | Role |
|---|---|---|
| EKS | K8s 1.32, 2 node groups | Container orchestration |
| EC2 (API nodes) | t3.medium × 2–6 | FastAPI pods |
| EC2 (Worker nodes) | t3.large × 1–4 | Embedding/SQS worker |
| RDS | db.t3.medium, 20GB gp3 | Primary database |
| ElastiCache | cache.t3.micro | Redis similarity cache |
| ALB | Internet-facing | HTTPS ingress |
| SQS | 2 queues + 2 DLQs | Async notifications |
| ECR | 3 repositories | Docker image registry |
| Secrets Manager | 4 secrets | Credential storage |
| S3 | 2 buckets | State + assets |
| CloudWatch | Logs + alarms | Observability |
