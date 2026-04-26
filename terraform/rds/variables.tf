variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "infragpt"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

# VPC inputs — pass from vpc module outputs or set manually
variable "vpc_id" {
  description = "VPC ID for the RDS security group"
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the DB subnet group"
  type        = list(string)
  default     = []
}

variable "vpc_cidr_block" {
  description = "VPC CIDR block for the RDS ingress rule"
  type        = string
  default     = "10.0.0.0/16"
}
