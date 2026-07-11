# =============================================================================
# NISCHINT - CloudWatch Monitoring Module Variables
# =============================================================================

variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aurora_cluster_id" {
  description = "Aurora cluster identifier for DB alarms"
  type        = string
}

variable "sns_alert_email" {
  description = "Email address for alarm notifications"
  type        = string
}

variable "api_latency_threshold_ms" {
  description = "API latency alarm threshold (milliseconds)"
  type        = number
  default     = 2000
}

variable "db_connections_threshold" {
  description = "DB connections alarm threshold"
  type        = number
  default     = 15
}

variable "db_cpu_threshold" {
  description = "DB CPU utilization alarm threshold (%)"
  type        = number
  default     = 80
}
