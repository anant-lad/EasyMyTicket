output "vpc_id" {
  value = aws_vpc.main.id
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "rds_endpoint" {
  value       = aws_db_instance.postgres.endpoint
  description = "RDS PostgreSQL endpoint (host:port)"
}

output "rds_db_name" {
  value = aws_db_instance.postgres.db_name
}

output "rds_secret_arn" {
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
  description = "Secrets Manager ARN holding RDS master password"
}

output "redis_endpoint" {
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
  description = "ElastiCache Redis primary endpoint"
}

output "sqs_notification_url" {
  value = aws_sqs_queue.notification.url
}

output "sqs_llm_url" {
  value = aws_sqs_queue.llm_jobs.url
}

output "s3_datasets_bucket" {
  value = aws_s3_bucket.datasets.id
}

output "s3_exports_bucket" {
  value = aws_s3_bucket.exports.id
}

output "ecr_api_url" {
  value = aws_ecr_repository.repos["ticketing-api"].repository_url
}

output "ecr_worker_url" {
  value = aws_ecr_repository.repos["ticket-worker"].repository_url
}

output "ecr_agent_url" {
  value = aws_ecr_repository.repos["ticket-agent"].repository_url
}

output "ticketing_pod_role_arn" {
  value       = aws_iam_role.ticketing_pod.arn
  description = "IRSA role ARN — annotate K8s ServiceAccount with this"
}

output "update_kubeconfig_command" {
  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}
