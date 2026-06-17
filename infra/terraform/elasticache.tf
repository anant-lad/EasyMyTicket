resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.name_prefix}-redis-subnet-group"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${local.name_prefix}-redis-subnet-group" }
}

resource "aws_elasticache_parameter_group" "redis7" {
  name   = "${local.name_prefix}-redis7"
  family = "redis7"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "Redis cache for ticketing platform"

  node_type            = var.elasticache_node_type
  num_cache_clusters   = 1   # single node for prod (increase to 2 for HA)
  port                 = 6379
  engine_version       = "7.1"
  parameter_group_name = aws_elasticache_parameter_group.redis7.name

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.elasticache.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result

  automatic_failover_enabled = false  # requires num_cache_clusters >= 2

  snapshot_retention_limit = 1
  snapshot_window          = "03:00-04:00"

  tags = { Name = "${local.name_prefix}-redis" }
}

resource "random_password" "redis_auth" {
  length  = 32
  special = false
}

# Store Redis auth token in Secrets Manager
resource "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id = aws_secretsmanager_secret.redis_auth.id
  secret_string = jsonencode({
    auth_token = random_password.redis_auth.result
    endpoint   = aws_elasticache_replication_group.main.primary_endpoint_address
    port       = 6379
  })
}

resource "aws_secretsmanager_secret" "redis_auth" {
  name                    = "/${var.project_name}/${var.environment}/redis-credentials"
  description             = "Redis auth token and endpoint"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}
