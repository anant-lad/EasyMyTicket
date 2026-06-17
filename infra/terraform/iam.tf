# ── IRSA: Pod IAM Role for ticketing-api and ticket-worker ───────────────────

resource "aws_iam_role" "ticketing_pod" {
  name = "${local.name_prefix}-pod-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = module.eks.oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringLike = {
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:ticketing:*"
        }
      }
    }]
  })
}

resource "aws_iam_policy" "ticketing_pod" {
  name        = "${local.name_prefix}-pod-policy"
  description = "Permissions for ticketing pods: Secrets Manager, SQS, S3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:/${var.project_name}/${var.environment}/*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:/rds!*"
        ]
      },
      {
        Sid    = "SQSAccess"
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = [
          aws_sqs_queue.notification.arn,
          aws_sqs_queue.llm_jobs.arn
        ]
      },
      {
        Sid    = "S3DatasetRead"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.datasets.arn,
          "${aws_s3_bucket.datasets.arn}/*"
        ]
      },
      {
        Sid    = "S3ExportsWrite"
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.exports.arn,
          "${aws_s3_bucket.exports.arn}/*"
        ]
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/ticketing/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ticketing_pod" {
  role       = aws_iam_role.ticketing_pod.name
  policy_arn = aws_iam_policy.ticketing_pod.arn
}

# ── CI/CD Deploy Role (used by GitHub Actions) ────────────────────────────────

resource "aws_iam_user" "cicd" {
  name = "${local.name_prefix}-cicd-user"
  tags = local.common_tags
}

resource "aws_iam_policy" "cicd" {
  name        = "${local.name_prefix}-cicd-policy"
  description = "GitHub Actions: ECR push + EKS deploy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRAuth"
        Effect = "Allow"
        Action = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage"
        ]
        Resource = [for r in aws_ecr_repository.repos : r.arn]
      },
      {
        Sid    = "EKSDescribe"
        Effect = "Allow"
        Action = ["eks:DescribeCluster"]
        Resource = "arn:aws:eks:${var.aws_region}:${var.aws_account_id}:cluster/${local.name_prefix}-cluster"
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "cicd" {
  user       = aws_iam_user.cicd.name
  policy_arn = aws_iam_policy.cicd.arn
}
