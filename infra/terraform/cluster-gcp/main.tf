provider "google" {
  project = var.project
  region  = var.region
  zone    = var.zone
}

locals {
  operator_cidrs = distinct(concat([var.operator_cidr], var.additional_operator_cidrs))
}

resource "google_compute_network" "g15" {
  name                    = "g15"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "g15" {
  name          = "g15"
  region        = var.region
  network       = google_compute_network.g15.id
  ip_cidr_range = var.subnet_cidr
}

# Node-to-node traffic (kubelet, etcd, Calico encapsulation).
resource "google_compute_firewall" "internal" {
  name    = "g15-allow-internal"
  network = google_compute_network.g15.id

  allow {
    protocol = "tcp"
  }
  allow {
    protocol = "udp"
  }
  allow {
    protocol = "icmp"
  }
  allow {
    protocol = "ipip"
  }

  source_ranges = [var.subnet_cidr]
}

# Operator-only management access. Never 0.0.0.0/0.
resource "google_compute_firewall" "ssh" {
  name          = "g15-allow-ssh"
  network       = google_compute_network.g15.id
  target_tags   = ["g15-node"]
  source_ranges = local.operator_cidrs

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "api" {
  name          = "g15-allow-api"
  network       = google_compute_network.g15.id
  target_tags   = ["g15-control-plane"]
  source_ranges = local.operator_cidrs

  allow {
    protocol = "tcp"
    ports    = ["6443"]
  }
}

resource "google_compute_firewall" "nodeport" {
  name          = "g15-allow-nodeport"
  network       = google_compute_network.g15.id
  target_tags   = ["g15-node"]
  source_ranges = distinct(concat(local.operator_cidrs, var.app_client_cidrs))

  allow {
    protocol = "tcp"
    ports    = ["30080"]
  }
}

resource "google_compute_address" "control_plane" {
  name   = "g15-cp1"
  region = var.region
}

resource "google_compute_instance" "control_plane" {
  count                     = var.control_plane_count
  name                      = "g15-cp${count.index + 1}"
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  zone                      = var.zone
  tags                      = ["g15-node", "g15-control-plane"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = var.disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.g15.id
    network_ip = var.control_plane_ip
    access_config {
      nat_ip = google_compute_address.control_plane.address
    }
  }

  metadata = {
    ssh-keys = "ubuntu:${var.ssh_public_key}"
  }
}

resource "google_compute_instance" "worker" {
  count                     = var.worker_count
  name                      = "g15-worker${count.index + 1}"
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  zone                      = var.zone
  tags                      = ["g15-node"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = var.disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.g15.id
    network_ip = var.worker_ips[count.index]
    access_config {}
  }

  metadata = {
    ssh-keys = "ubuntu:${var.ssh_public_key}"
  }
}
