# =============================================================================
# NISCHINT - CloudWatch Monitoring Module
# =============================================================================

# -----------------------------------------------------------------------------
# SNS Topic for Alarm Notifications
# -----------------------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name = "${var.project}-${var.environment}-alerts"

  tags = {
    Name = "${var.project}-${var.environment}-alerts"
  }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.sns_alert_email
}

# -----------------------------------------------------------------------------
# Aurora DB Alarms
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "aurora_cpu" {
  alarm_name          = "${var.project}-${var.environment}-aurora-cpu-high"
  alarm_description   = "Aurora CPU utilization exceeds ${var.db_cpu_threshold}%"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = var.db_cpu_threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBClusterIdentifier = var.aurora_cluster_id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.project}-${var.environment}-aurora-cpu-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "aurora_connections" {
  alarm_name          = "${var.project}-${var.environment}-aurora-connections-high"
  alarm_description   = "Aurora DB connections exceed ${var.db_connections_threshold}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = var.db_connections_threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBClusterIdentifier = var.aurora_cluster_id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.project}-${var.environment}-aurora-connections-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "aurora_freeable_memory" {
  alarm_name          = "${var.project}-${var.environment}-aurora-memory-low"
  alarm_description   = "Aurora freeable memory below 256MB"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "FreeableMemory"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 268435456
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBClusterIdentifier = var.aurora_cluster_id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.project}-${var.environment}-aurora-memory-alarm"
  }
}

# -----------------------------------------------------------------------------
# Custom Application Metrics (pushed by backend)
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "app" {
  name              = "/nischint/${var.environment}/application"
  retention_in_days = 30

  tags = {
    Name = "${var.project}-${var.environment}-app-logs"
  }
}

resource "aws_cloudwatch_metric_alarm" "sos_spike" {
  alarm_name          = "${var.project}-${var.environment}-sos-trigger-spike"
  alarm_description   = "SOS triggers exceeded 5 in 5 minutes — possible emergency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "SOSTriggerCount"
  namespace           = "Nischint/${var.environment}"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.project}-${var.environment}-sos-spike-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${var.project}-${var.environment}-api-latency-high"
  alarm_description   = "API p95 latency exceeds ${var.api_latency_threshold_ms}ms"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "APILatencyP95"
  namespace           = "Nischint/${var.environment}"
  period              = 60
  statistic           = "Maximum"
  threshold           = var.api_latency_threshold_ms
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.project}-${var.environment}-api-latency-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "api_error_rate" {
  alarm_name          = "${var.project}-${var.environment}-api-error-rate-high"
  alarm_description   = "API 5xx error rate exceeds 10 per minute"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "APIErrorCount5xx"
  namespace           = "Nischint/${var.environment}"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.project}-${var.environment}-api-error-rate-alarm"
  }
}
