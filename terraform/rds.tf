
resource "aws_db_instance" "postgres" {
  identifier = "${var.project_name}-postgres"

  engine         = "postgres"
  engine_version = "17"
  instance_class = var.rds_instance_class

  allocated_storage = 20
  storage_type      = "gp2"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username

  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  publicly_accessible = false
  multi_az            = false

  backup_retention_period = 1
  deletion_protection     = true

  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project_name}-final"

  auto_minor_version_upgrade = true

  tags = {
    Name = "${var.project_name}-postgres"
  }
}
