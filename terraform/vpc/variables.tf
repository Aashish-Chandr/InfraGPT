variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name of the project, used as prefix for all resources"
  type        = string
  default     = "infragpt"
}

variable "environment" {
  description = "Deployment environment (local, staging, production)"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["local", "staging", "production"], var.environment)
    error_message = "Environment must be one of: local, staging, production."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}
