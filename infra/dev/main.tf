# =============================================================================
# NISCHINT - Dev Environment Main Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# VPC
# -----------------------------------------------------------------------------
module "vpc" {
  source = "../modules/vpc"

  project     = "nischint"
  environment = "dev"

  vpc_cidr           = "10.10.0.0/16"
  availability_zones = ["ap-south-1a", "ap-south-1b"]

  public_subnet_cidrs  = ["10.10.1.0/24", "10.10.2.0/24"]
  private_subnet_cidrs = ["10.10.10.0/24", "10.10.11.0/24"]

  enable_nat_gateway = true
}

# -----------------------------------------------------------------------------
# Application Security Group (ECS tasks / backend services)
# -----------------------------------------------------------------------------
resource "aws_security_group" "app" {
  name        = "nischint-dev-app-sg"
  description = "Security group for NISCHINT application services (ECS)"
  vpc_id      = module.vpc.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "nischint-dev-app-sg"
  }
}

# -----------------------------------------------------------------------------
# Aurora PostgreSQL Serverless v2
# -----------------------------------------------------------------------------
module "aurora" {
  source = "../modules/aurora"

  project     = "nischint"
  environment = "dev"

  vpc_id                     = module.vpc.vpc_id
  allowed_security_group_ids = [aws_security_group.app.id]
  subnet_ids                 = module.vpc.private_subnet_ids

  engine_version  = "15.3"
  database_name   = "nischint"
  master_username = "nischint_admin"
  master_password = var.db_password

  min_capacity = 0.5
  max_capacity = 2

  backup_retention_period      = 7
  deletion_protection          = false
  performance_insights_enabled = true
}

# -----------------------------------------------------------------------------
# CloudWatch Monitoring
# -----------------------------------------------------------------------------
module "monitoring" {
  source = "../modules/monitoring"

  project     = "nischint"
  environment = "dev"

  aurora_cluster_id = module.aurora.cluster_id
  sns_alert_email   = var.alert_email
}

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------
variable "db_password" {
  description = "Aurora master password"
  type        = string
  sensitive   = true
}

variable "alert_email" {
  description = "Email for CloudWatch alarm notifications"
  type        = string
  default     = "nischint4parents@gmail.com"
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "VPC CIDR"
  value       = module.vpc.vpc_cidr
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnet_ids
}

output "nat_gateway_public_ip" {
  description = "NAT Gateway public IP"
  value       = module.vpc.nat_gateway_public_ip
}

output "aurora_cluster_endpoint" {
  description = "Aurora cluster endpoint"
  value       = module.aurora.cluster_endpoint
}

output "aurora_reader_endpoint" {
  description = "Aurora reader endpoint"
  value       = module.aurora.cluster_reader_endpoint
}

output "aurora_port" {
  description = "Aurora port"
  value       = module.aurora.cluster_port
}

output "aurora_database_name" {
  description = "Aurora database name"
  value       = module.aurora.database_name
}

output "aurora_security_group_id" {
  description = "Aurora security group ID"
  value       = module.aurora.security_group_id
}

output "aurora_secret_arn" {
  description = "Aurora password secret ARN"
  value       = module.aurora.secret_arn
}

output "app_security_group_id" {
  description = "Application security group ID (for ECS tasks)"
  value       = aws_security_group.app.id
}

output "monitoring_sns_topic_arn" {
  description = "SNS topic ARN for alerts"
  value       = module.monitoring.sns_topic_arn
}
