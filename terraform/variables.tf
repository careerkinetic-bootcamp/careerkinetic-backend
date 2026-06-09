variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "gcp_region" {
  description = "GCP region (targeting Asia for low latency)"
  type        = string
  default     = "asia-south1"
}

variable "app_name" {
  description = "Name of the application"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "supabase_db_url" {
  description = "Supabase PostgreSQL connection string"
  type        = string
  sensitive   = true
}

variable "supabase_url" {
  description = "Supabase project URL (e.g., https://xxxx.supabase.co)"
  type        = string
}

variable "supabase_anon_key" {
  description = "Supabase public anonymous API key"
  type        = string
  sensitive   = true
}

variable "supabase_service_role_key" {
  description = "Supabase private service role key"
  type        = string
  sensitive   = true
}

variable "supabase_jwt_secret" {
  description = "Supabase JWT signing secret"
  type        = string
  sensitive   = true
}
