# =============================================================================
# NISCHINT - Aurora Module Outputs
# =============================================================================

output "cluster_id" {
  description = "Aurora cluster ID"
  value       = aws_rds_cluster.this.id
}

output "cluster_arn" {
  description = "Aurora cluster ARN"
  value       = aws_rds_cluster.this.arn
}

output "cluster_endpoint" {
  description = "Aurora cluster endpoint (writer)"
  value       = aws_rds_cluster.this.endpoint
}

output "cluster_reader_endpoint" {
  description = "Aurora cluster reader endpoint"
  value       = aws_rds_cluster.this.reader_endpoint
}

output "cluster_port" {
  description = "Aurora cluster port"
  value       = aws_rds_cluster.this.port
}

output "database_name" {
  description = "Database name"
  value       = aws_rds_cluster.this.database_name
}

output "master_username" {
  description = "Master username"
  value       = aws_rds_cluster.this.master_username
}

output "security_group_id" {
  description = "Aurora security group ID"
  value       = aws_security_group.this.id
}

output "db_subnet_group_name" {
  description = "DB subnet group name"
  value       = aws_db_subnet_group.this.name
}

output "secret_arn" {
  description = "Secrets Manager secret ARN for DB password"
  value       = aws_secretsmanager_secret.db_password.arn
}
