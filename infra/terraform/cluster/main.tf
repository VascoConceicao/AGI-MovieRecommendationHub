provider "libvirt" {
  uri = var.libvirt_uri
}

resource "libvirt_network" "g15" {
  name      = "g15"
  mode      = "nat"
  domain    = "g15.local"
  addresses = [var.network_cidr]

  dhcp {
    enabled = true
  }

  dns {
    enabled = true
  }
}

resource "libvirt_volume" "base" {
  name   = "g15-ubuntu-24.04-base"
  pool   = "default"
  source = var.base_image
  format = "qcow2"
}

resource "libvirt_volume" "control_plane" {
  count          = var.control_plane_count
  name           = "g15-cp${count.index + 1}.qcow2"
  pool           = "default"
  base_volume_id = libvirt_volume.base.id
  size           = var.node_disk_bytes
  format         = "qcow2"
}

resource "libvirt_volume" "worker" {
  count          = var.worker_count
  name           = "g15-worker${count.index + 1}.qcow2"
  pool           = "default"
  base_volume_id = libvirt_volume.base.id
  size           = var.node_disk_bytes
  format         = "qcow2"
}

resource "libvirt_cloudinit_disk" "control_plane" {
  count = var.control_plane_count
  name  = "g15-cp${count.index + 1}-seed.iso"
  pool  = "default"
  user_data = templatefile("${path.module}/templates/cloud-init.yaml", {
    hostname       = "g15-cp${count.index + 1}"
    ssh_public_key = var.ssh_public_key
  })
}

resource "libvirt_cloudinit_disk" "worker" {
  count = var.worker_count
  name  = "g15-worker${count.index + 1}-seed.iso"
  pool  = "default"
  user_data = templatefile("${path.module}/templates/cloud-init.yaml", {
    hostname       = "g15-worker${count.index + 1}"
    ssh_public_key = var.ssh_public_key
  })
}

resource "libvirt_domain" "control_plane" {
  count       = var.control_plane_count
  name        = "g15-cp${count.index + 1}"
  memory      = var.vm_memory_mb
  vcpu        = var.vm_vcpu
  type        = "kvm"
  qemu_agent  = false
  fw_cfg_name = "opt/com.coreos/config"

  cpu {
    mode = "host-passthrough"
  }

  cloudinit = libvirt_cloudinit_disk.control_plane[count.index].id

  disk {
    volume_id = libvirt_volume.control_plane[count.index].id
  }

  network_interface {
    network_id     = libvirt_network.g15.id
    mac            = "52:54:00:22:67:AD"
    wait_for_lease = true
  }

  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }
}

resource "libvirt_domain" "worker" {
  count       = var.worker_count
  name        = "g15-worker${count.index + 1}"
  memory      = var.vm_memory_mb
  vcpu        = var.vm_vcpu
  type        = "kvm"
  qemu_agent  = false
  fw_cfg_name = "opt/com.coreos/config"

  cpu {
    mode = "host-passthrough"
  }

  cloudinit = libvirt_cloudinit_disk.worker[count.index].id

  disk {
    volume_id = libvirt_volume.worker[count.index].id
  }

  network_interface {
    network_id     = libvirt_network.g15.id
    mac            = var.worker_macs[count.index]
    wait_for_lease = true
  }

  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }
}
