variable "gcp_project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "gcp_region" {
  description = "GCP region (targeting Asia for low latency)"
  type        = string
  default     = "asia-south2"
}

variable "app_name" {
  description = "Name of the application"
  type        = string
  default     = "careerkinetic"
}

variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "database_url" {
  description = "Connection string for the PostgreSQL database (logical database)"
  type        = string
  sensitive   = true
}

variable "jwt_secret" {
  description = "Secret key used to sign custom JWT tokens"
  type        = string
  sensitive   = true
}

variable "cors_origins" {
  description = "CORS allowed origins for the frontend"
  type        = list(string)
  default     = ["http://localhost:5173", "http://127.0.0.1:5173"]
}

# --- Google OAuth ---
variable "google_client_id" {
  description = "Google Client ID"
  type        = string
}

variable "google_client_secret" {
  description = "Google Client Secret"
  type        = string
  sensitive   = true
}

variable "google_redirect_uri" {
  description = "Google Redirect Callback URI"
  type        = string
}

# --- GitHub OAuth ---
variable "github_client_id" {
  description = "GitHub Client ID"
  type        = string
}

variable "github_client_secret" {
  description = "GitHub Client Secret"
  type        = string
  sensitive   = true
}

variable "github_redirect_uri" {
  description = "GitHub Redirect Callback URI"
  type        = string
}

variable "cloud_sql_instance" {
  description = "Connection name of the Cloud SQL instance (e.g. project:region:instance)"
  type        = string
  default     = ""
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}
