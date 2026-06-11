terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "careerkinetic-tf-state"
    prefix = "state/backend"
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

locals {
  name_prefix = "${var.app_name}-${var.environment}"
}

# --- Artifact Registry (Docker images) ---
resource "google_artifact_registry_repository" "app" {
  location      = var.gcp_region
  repository_id = "${var.app_name}-${var.environment}-repo"
  format        = "DOCKER"
  description   = "Docker repository for ${var.app_name} (${var.environment})"

  # Prevent deletion conflict when applying dev and prod separately
  lifecycle {
    prevent_destroy = false
  }
}

# --- Cloud Run Service ---
resource "google_cloud_run_v2_service" "api" {
  name     = local.name_prefix
  location = var.gcp_region

  template {
    containers {
      image = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project_id}/${google_artifact_registry_repository.app.repository_id}/${var.app_name}:latest"

      ports {
        container_port = 8080
      }

      env {
        name  = "ENV"
        value = var.environment
      }
      env {
        name  = "DATABASE_URL"
        value = var.database_url
      }
      env {
        name  = "JWT_SECRET"
        value = var.jwt_secret
      }
      env {
        name  = "CORS_ORIGINS"
        value = jsonencode(var.cors_origins)
      }
      env {
        name  = "GOOGLE_CLIENT_ID"
        value = var.google_client_id
      }
      env {
        name  = "GOOGLE_CLIENT_SECRET"
        value = var.google_client_secret
      }
      env {
        name  = "GOOGLE_REDIRECT_URI"
        value = var.google_redirect_uri
      }
      env {
        name  = "GITHUB_CLIENT_ID"
        value = var.github_client_id
      }
      env {
        name  = "GITHUB_CLIENT_SECRET"
        value = var.github_client_secret
      }
      env {
        name  = "GITHUB_REDIRECT_URI"
        value = var.github_redirect_uri
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
  }
}

# --- Allow unauthenticated access (public API) ---
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.gcp_region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "cloud_run_url" {
  value       = google_cloud_run_v2_service.api.uri
  description = "The public URL of the Cloud Run service"
}
