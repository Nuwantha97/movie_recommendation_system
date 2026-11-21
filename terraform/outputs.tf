
output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_id" {
  value = aws_subnet.public.id
}

output "db_subnet_group_name" {
  value = aws_db_subnet_group.main.name
}

output "ec2_security_group_id" {
  value = aws_security_group.ec2.id
}

output "rds_security_group_id" {
  value = aws_security_group.rds.id
}

output "ec2_instance_id" {
  value = aws_instance.backend.id
}

output "ec2_public_ip" {
  value = aws_eip.backend.public_ip
}

output "release_bucket" {
  value = aws_s3_bucket.releases.id
}

output "runtime_secret_name" {
  value = local.runtime_secret_name
}

output "rds_endpoint" {
  value = aws_db_instance.postgres.address
}

output "rds_port" {
  value = aws_db_instance.postgres.port
}

output "rds_master_secret_arn" {
  value = aws_db_instance.postgres.master_user_secret[0].secret_arn
}
