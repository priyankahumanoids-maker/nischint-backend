# =============================================================================
# NISCHINT - Aurora PostgreSQL Serverless v2 Module
# =============================================================================

# -----------------------------------------------------------------------------
# DB Subnet Group
# -----------------------------------------------------------------------------
resource "aws_db_subnet_group" "this" {
  name       = "${var.project}-${var.environment}-aurora"
  subnet_ids = var.subnet_ids

  tags = {
    Name = "${var.project}-${var.environment}-aurora-subnet-group"
  }
}

# -----------------------------------------------------------------------------
# Cluster Parameter Group
# -----------------------------------------------------------------------------
resource "aws_rds_cluster_parameter_group" "this" {
  name        = "${var.project}-${var.environment}-aurora-pg15"
  family      = "aurora-postgresql15"
  description = "Aurora PostgreSQL 15 parameter group for ${var.project} ${var.environment}"

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  tags = {
    Name = "${var.project}-${var.environment}-aurora-pg15"
  }
}

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------
resource "aws_security_group" "this" {
  name        = "${var.project}-${var.environment}-aurora-sg"
  description = "Security group for Aurora PostgreSQL"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from application security groups only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = var.allowed_security_group_ids
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-aurora-sg"
  }
}

# -----------------------------------------------------------------------------
# Secrets Manager - Store Master Password
# -----------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.project}-${var.environment}-db-password"
  description             = "Aurora master password for ${var.project} ${var.environment}"
  recovery_window_in_days = 0

  tags = {
    Name = "${var.project}-${var.environment}-db-password"
  }
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = var.master_password
}

# -----------------------------------------------------------------------------
# Aurora Cluster
# -----------------------------------------------------------------------------
resource "aws_rds_cluster" "this" {
  cluster_identifier = "${var.project}-${var.environment}"

  engine         = "aurora-postgresql"
  engine_mode    = "provisioned"
  engine_version = var.engine_version

  database_name   = var.database_name
  master_username = var.master_username
  master_password = var.master_password

  db_subnet_group_name            = aws_db_subnet_group.this.name
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.this.name
  vpc_security_group_ids          = [aws_security_group.this.id]

  serverlessv2_scaling_configuration {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }

  iam_database_authentication_enabled = true
  storage_encrypted                   = true

  backup_retention_period = var.backup_retention_period
  preferred_backup_window = "03:00-04:00"

  deletion_protection = var.deletion_protection
  skip_final_snapshot = true
  apply_immediately   = true

  tags = {
    Name = "${var.project}-${var.environment}-aurora-cluster"
  }
}

# -----------------------------------------------------------------------------
# Aurora Instance
# -----------------------------------------------------------------------------
resource "aws_rds_cluster_instance" "this" {
  identifier         = "${var.project}-${var.environment}-1"
  cluster_identifier = aws_rds_cluster.this.id

  instance_class = "db.serverless"
  engine         = aws_rds_cluster.this.engine
  engine_version = aws_rds_cluster.this.engine_version

  publicly_accessible            = false
  auto_minor_version_upgrade     = false
  performance_insights_enabled   = var.performance_insights_enabled

  tags = {
    Name = "${var.project}-${var.environment}-aurora-instance-1"
  }
}
