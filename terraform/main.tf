terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "careerkinetic-terraform-state"
    prefix = "state"
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
  repository_id = "${var.app_name}-repo"
  format        = "DOCKER"
  description   = "Docker repository for ${var.app_name}"
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
        value = var.supabase_db_url
      }
      env {
        name  = "SUPABASE_URL"
        value = var.supabase_url
      }
      env {
        name  = "SUPABASE_ANON_KEY"
        value = var.supabase_anon_key
      }
      env {
        name  = "SUPABASE_SERVICE_ROLE_KEY"
        value = var.supabase_service_role_key
      }
      env {
        name  = "SUPABASE_JWT_SECRET"
        value = var.supabase_jwt_secret
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
