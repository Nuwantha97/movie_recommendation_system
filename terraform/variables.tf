
variable "project_name" {
  type    = string
  default = "movie-recommendation"
}


variable "aws_region" {
  description = "AWS region for the movie recommendation system"
  type        = string
  default     = "ap-southeast-2"
}


variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "ec2_instance_type" {
  type    = string
  default = "m7i-flex.large"
}

variable "rds_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "db_name" {
  type    = string
  default = "moviedb"
}

variable "db_username" {
  type    = string
  default = "movieadmin"
}
