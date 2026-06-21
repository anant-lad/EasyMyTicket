variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-south-1"
}

variable "aws_account_id" {
  description = "AWS account ID"
  type        = string
  default     = "808812816838"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "ticketing"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones"
  type        = list(string)
  default     = ["ap-south-1a", "ap-south-1b"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.3.0/24", "10.0.4.0/24"]
}

variable "eks_cluster_version" {
  description = "EKS Kubernetes version"
  type        = string
  default     = "1.32"
}

variable "api_node_instance_type" {
  description = "EC2 instance type for API node group"
  type        = string
  default     = "t3.medium"
}

variable "worker_node_instance_type" {
  description = "EC2 instance type for worker node group (needs more RAM for embeddings)"
  type        = string
  default     = "t3.large"
}

variable "api_node_min" {
  type    = number
  default = 2
}

variable "api_node_max" {
  type    = number
  default = 6
}

variable "api_node_desired" {
  type    = number
  default = 2
}

variable "worker_node_min" {
  type    = number
  default = 1
}

variable "worker_node_max" {
  type    = number
  default = 3
}

variable "worker_node_desired" {
  type    = number
  default = 1
}

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "rds_allocated_storage" {
  description = "RDS storage in GB"
  type        = number
  default     = 100
}

variable "rds_db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "tickets_db"
}

variable "rds_username" {
  description = "RDS master username"
  type        = string
  default     = "ticketing_admin"
}

variable "rds_master_password" {
  description = "RDS master password (static, rotation disabled)"
  type        = string
  sensitive   = true
}

variable "elasticache_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "alarm_email" {
  description = "Email for CloudWatch alarm notifications"
  type        = string
  default     = "anantlad0628@gmail.com"
}
