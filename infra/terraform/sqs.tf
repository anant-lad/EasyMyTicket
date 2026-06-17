# ── Dead Letter Queues ────────────────────────────────────────────────────────

resource "aws_sqs_queue" "notification_dlq" {
  name                      = "${local.name_prefix}-notification-dlq"
  message_retention_seconds = 1209600  # 14 days
  tags                      = local.common_tags
}

resource "aws_sqs_queue" "llm_dlq" {
  name                      = "${local.name_prefix}-llm-dlq"
  message_retention_seconds = 1209600
  tags                      = local.common_tags
}

# ── Main Queues ───────────────────────────────────────────────────────────────

resource "aws_sqs_queue" "notification" {
  name                       = "${local.name_prefix}-notification-queue"
  visibility_timeout_seconds = 120    # 2min — time for email worker to process
  message_retention_seconds  = 86400  # 1 day
  receive_wait_time_seconds  = 20     # long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notification_dlq.arn
    maxReceiveCount     = 3
  })

  tags = local.common_tags
}

resource "aws_sqs_queue" "llm_jobs" {
  name                       = "${local.name_prefix}-llm-queue"
  visibility_timeout_seconds = 300    # 5min — LLM calls can take time
  message_retention_seconds  = 3600   # 1 hour

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.llm_dlq.arn
    maxReceiveCount     = 2
  })

  tags = local.common_tags
}

# ── Queue policies (allow EKS pods via IRSA) ─────────────────────────────────

resource "aws_sqs_queue_policy" "notification" {
  queue_url = aws_sqs_queue.notification.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.ticketing_pod.arn }
      Action    = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource  = aws_sqs_queue.notification.arn
    }]
  })
}

resource "aws_sqs_queue_policy" "llm_jobs" {
  queue_url = aws_sqs_queue.llm_jobs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.ticketing_pod.arn }
      Action    = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource  = aws_sqs_queue.llm_jobs.arn
    }]
  })
}
