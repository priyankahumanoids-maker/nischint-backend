# =============================================================================
# NISCHINT - Aurora Module Variables
# =============================================================================

variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "allowed_security_group_ids" {
  description = "List of security group IDs allowed to access Aurora (e.g., ECS app SG)"
  type        = list(string)
}

variable "subnet_ids" {
  description = "List of subnet IDs for DB subnet group"
  type        = list(string)
}

variable "engine_version" {
  description = "Aurora PostgreSQL engine version (pinned to prevent auto-upgrades)"
  type        = string
  default     = "15.3"
}

variable "database_name" {
  description = "Name of the default database"
  type        = string
  default     = "nischint"
}

variable "master_username" {
  description = "Master username"
  type        = string
  default     = "nischint_admin"
}

variable "master_password" {
  description = "Master password"
  type        = string
  sensitive   = true
}

variable "min_capacity" {
  description = "Minimum ACU capacity"
  type        = number
  default     = 0.5
}

variable "max_capacity" {
  description = "Maximum ACU capacity"
  type        = number
  default     = 2
}

variable "backup_retention_period" {
  description = "Backup retention period in days"
  type        = number
  default     = 7
}

variable "deletion_protection" {
  description = "Enable deletion protection"
  type        = bool
  default     = false
}

variable "performance_insights_enabled" {
  description = "Enable Performance Insights"
  type        = bool
  default     = true
}
