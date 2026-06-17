aws_region     = "ap-south-1"
aws_account_id = "808812816838"
project_name   = "ticketing"
environment    = "prod"

# Network
vpc_cidr             = "10.0.0.0/16"
availability_zones   = ["ap-south-1a", "ap-south-1b"]
public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
private_subnet_cidrs = ["10.0.3.0/24", "10.0.4.0/24"]

# EKS
eks_cluster_version       = "1.32"
api_node_instance_type    = "t3.medium"
worker_node_instance_type = "t3.large"
api_node_min              = 2
api_node_max              = 6
api_node_desired          = 2
worker_node_min           = 1
worker_node_max           = 3
worker_node_desired       = 1

# RDS
rds_instance_class    = "db.t3.medium"
rds_allocated_storage = 100
rds_db_name           = "tickets_db"
rds_username          = "ticketing_admin"

# ElastiCache
elasticache_node_type = "cache.t3.micro"

# Monitoring
alarm_email = "anantlad0628@gmail.com"
