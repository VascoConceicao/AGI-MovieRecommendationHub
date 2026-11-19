# Infrastructure

## CI runner

[CI setup and scripts](ci-cd/README.md) live in `infra/ci-cd/`.
The test runner uses the existing Kubernetes cluster, up to two jobs at a time.
Tests run for pushes and merges to `development` or `master` (not for merge
requests). On `master`, the pipeline then builds six images with Kaniko,
publishes them with Skopeo to the GitLab Container Registry by digest, and
deploys them automatically (`deploy:dry-run`, `deploy:production`, manual
`deploy:rollback`). The initial infrastructure below is built by hand; all later
application updates are deployed by this pipeline.

## Prerequisites

The cluster infrastructure is currently designed for a Linux host using KVM/libvirt.

Install:

- Terraform >= 1.9
- libvirt
- QEMU/KVM
- dnsmasq
- virt-install
- cdrtools (`mkisofs`)
- An Ubuntu 24.04 Server cloud image

On Arch Linux:

sudo pacman -S --needed qemu-desktop libvirt virt-install dnsmasq cdrtools

Enable libvirt:

sudo systemctl enable --now libvirtd.service

Add the current user to the libvirt group:

sudo usermod -aG libvirt "$USER"

Log out and back in (or start a new login shell) after changing group membership.

The Ubuntu cloud image must be available at:

/var/lib/libvirt/images/ubuntu-24.04-server-cloudimg-amd64.img

### Host networking

The libvirt network uses NAT through the host's Internet connection.
The host firewall must allow forwarding from the libvirt bridge (`virbr1`)
to the host's external interface.

If VMs receive an IP address but cannot reach the Internet, verify:

- IPv4 forwarding is enabled.
- The host firewall permits `virbr1` -> external-interface forwarding.
- The libvirt NAT rules are present.

## Architecture

```text
Terraform
   ↓
KVM/libvirt VMs
   ↓
Ansible
   ↓
kubeadm Kubernetes
   ↓
Terraform + Helm
   ↓
Application + monitoring/logging/ingress stack
```

Local VMs first; the same kubeadm flow migrates to public-cloud VMs by
replacing only the VM layer. Managed Kubernetes (GKE and equivalents) is
forbidden.

## What is live

3 nodes (1 control-plane + 2 workers; on GCE `e2-standard-2`, 2 vCPU and 8 GiB each) running Kubernetes
v1.36.5 with Calico; the full application (frontend, proxy, 3 Flask
services, 3 PostgreSQL databases) in `g15-app`; `kube-prometheus-stack`
plus the "G15 Services" dashboard, Loki + Alloy logging, and ingress-nginx
(`:30080` → proxy Ingress → proxy ClusterIP) in `g15-monitoring` /
`ingress-nginx`. Verified end to
end through the ingress entrypoint, including DB/backend pod-kill recovery
with data intact on PVCs. Details: `k8s/app/README.md`,
`k8s/monitoring/README.md`.

## Responsibilities

| Tool       | Responsibility                     |
| ---------- | ---------------------------------- |
| Terraform  | VM + Kubernetes resource lifecycle |
| Ansible    | OS configuration + kubeadm         |
| kubeadm    | Self-hosted Kubernetes bootstrap   |
| Helm       | Monitoring/logging/ingress packages|
| Prometheus | Metrics collection                 |
| Loki+Alloy | Log collection and storage         |
| Grafana    | Visualization (Prometheus+Loki)    |
| Ingress-NGINX | External entrypoint (:30080)    |
| Kustomize  | Application Kubernetes manifests   |

Data flow contract:

```text
Terraform cluster
      ↓
VM IP outputs
      ↓
Ansible
      ↓
kubeconfig.out
      ↓
Terraform app
```

## Execution order

```text
1. Terraform cluster (local libvirt VMs: 2 GiB by default, pinned MACs; the GCE layer uses `e2-standard-2`, 8 GiB)
2. Ansible node prep (containerd, Kubernetes v1.36 packages)
3. Ansible kubeadm bootstrap (init, Calico, join)
4. Terraform app (namespaces, kube-prometheus-stack + Loki + Alloy + ingress-nginx, ServiceMonitor, dashboard)
5. Kustomize app manifests (first install: images side-loaded, secrets from env file, incl. proxy Ingress, Qwen inference and the suspended agent CronJob)
6. Verify through the ingress entrypoint (:30080)
7. One-time CD setup (runners, pull credentials, `cd-state`), see ci-cd/README.md; from then on GitLab CI/CD deploys updates by image digest
```

Commits followed this order (skeleton → VMs → inventory → prep →
containerd → packages → VM pins → bootstrap → app stack → monitoring
stack → metrics → dashboard → GCE module → operator access → load
harness). Cloud credentials never enter the repository.

## Google Cloud track (provisioned, verified, destroyed)

A second cluster layer, `terraform/cluster-gcp`, reproduces the platform
on GCE while reusing everything above it unchanged (Ansible, manifests,
app Terraform layer, images, monitoring).

- 3× `e2-small` in `europe-southwest1-a` (Madrid), Ubuntu 24.04
  (`ubuntu-2404-lts-amd64` family — the short name does not resolve),
  20 GB balanced PDs, node subnet `10.42.42.0/24` with static internal
  IPs, one static external IP on the control plane.
- Split-brain addressing: kubeadm advertises the **internal** IP
  (node-to-node stays on the VPC); the **external** IP serves operator
  SSH/kubectl/NodePort only. The API certificate gains the external SAN
  via an idempotent playbook task (`kubeadm init phase certs` silently
  no-ops when files exist — the task removes them first), and the
  fetched kubeconfig is rewritten to the external server address.
  Firewall rules scope 22/6443/30080 to the operator IP — which must be
  IPv4 (`/32`); the host's IPv6 address does not route to the instances.
- kubeadm uses the Ansible inventory names for node registration. GCE's
  generated hostname can exceed Kubernetes' 63-byte hostname-label limit
  when the Google project ID is long.
- Distribution diverges from local: GCE egress is full, so only the
  five `:local` images ride the tarball; everything upstream pulls
  natively (no side-loading circus).
- Re-provision runbook (gotchas learned provisioning it):
  ```sh
  export TF_VAR_ssh_public_key="$(cat ~/.ssh/id_ed25519.pub)"
  export TF_VAR_operator_cidr="$(curl -s -4 ifconfig.me)/32"  # IPv4 only
  sh infra/terraform/tf-apply.sh infra/terraform/cluster-gcp -auto-approve
  # Refresh infra/ansible/inventory.gcp.ini from cluster-gcp outputs, wait for SSH,
  # then bootstrap. site.yaml var is kubeconfig_output (not kubeconfig_path),
  # and the advertise address must be the control-plane INTERNAL IP:
  ansible-playbook -i inventory.gcp.ini site.yaml \
    -e apiserver_advertise_address=10.42.42.10 \
    -e kubeconfig_output=$PWD/../terraform/cluster-gcp/kubeconfig.out
  ```
  Keep the app-layer GCE state in `.data-gcp` (gitignored) so the local
  `terraform.tfstate` is never clobbered:
  ```sh
  docker build -t g15-<component>:local ... # five images, tarball + ctr import
  kubectl apply -f <local-path-provisioner URL>  # GCE pulls natively
  terraform -chdir=infra/terraform/app apply \
    -state=$PWD/infra/terraform/app/.data-gcp/terraform.tfstate \
    -var=kubeconfig_path=../cluster-gcp/kubeconfig.out -auto-approve
  KUBECONFIG=infra/terraform/cluster-gcp/kubeconfig.out kubectl apply -k infra/k8s/app
  ```
  On a fresh cluster the `ServiceMonitor` apply races the Prometheus CRDs;
  apply the namespaces + `helm_release.*` targets first, then the full layer.
- Lifecycle completed end to end: provision → bootstrap → app +
  monitoring deploy → health/failure verification → synthetic load →
  `terraform destroy` with a zero-resource `gcloud` audit (no instances,
  disks, IPs, rules). Re-provision with the step 1–7 sequence; keep the
  GCE state out of git (`terraform/app/.data-gcp`, gitignored).

## Movie Recommendation System cloud deployment

The WSL operator setup uses Google project `prefab-conquest-511709-j5`
(Movie Recommendation System), separate from the Terraform default project
`g15-mlops`. It has one cloud environment: three `e2-standard-2` VMs in Madrid
(2 vCPU / 8 GiB per node).
Development stays local; the same cloud environment serves staging/demo.

VM type changes are allowed in place through Terraform. Resize one node at
a time, waiting for Kubernetes and app pods to recover before the next node.
The stop/start keeps existing boot disks and application data.

Operator files (credentials and state stay out of Git):

- Cluster variables: `~/.local/share/g15-deploy/prefab-conquest-511709-j5/cluster.tfvars.json`.
  This selects the project, SSH public key, and operator IPv4 CIDR.
- Cluster state: `infra/terraform/cluster-gcp/terraform.tfstate`.
- Kubernetes access: `infra/terraform/cluster-gcp/kubeconfig.out`.
- SSH inventory: `infra/ansible/inventory.gcp.ini`.
- Platform provider data:
  `~/.local/share/g15-deploy/prefab-conquest-511709-j5/app-plugins/`.
- Platform state:
  `~/.local/share/g15-deploy/prefab-conquest-511709-j5/platform.tfstate`.
- App secrets: `infra/k8s/app/db-passwords.env`.
- App manifests: `infra/k8s/overlays/demo` (HTTP cookie setting for this demo).

From the repository root:

```sh
export KUBECONFIG="$PWD/infra/terraform/cluster-gcp/kubeconfig.out"
kubectl get nodes
kubectl -n g15-app get pods,pvc
kubectl apply -k infra/k8s/overlays/demo
```

For cluster changes, pass the saved variables explicitly:

```sh
terraform -chdir=infra/terraform/cluster-gcp plan \
  -var-file="$HOME/.local/share/g15-deploy/prefab-conquest-511709-j5/cluster.tfvars.json"
```

Platform changes must use the same external provider-data directory and
state file, plus the GCP kubeconfig; do not use the local cluster's state:

```sh
export TF_DATA_DIR="$HOME/.local/share/g15-deploy/prefab-conquest-511709-j5/app-plugins"
terraform -chdir=infra/terraform/app plan \
  -state="$HOME/.local/share/g15-deploy/prefab-conquest-511709-j5/platform.tfstate" \
  -var=kubeconfig_path="$KUBECONFIG"
```

Keep both state files for future updates and teardown. SSH and Kubernetes
API access are limited to `operator_cidr` and `additional_operator_cidrs`.
Demo HTTP also allows `app_client_cidrs`. Update the relevant CIDRs through
Terraform when an allowed public IP changes.
The cloud VMs remain running and accrue costs until stopped or destroyed.

## Known limitations

- `dmacvicar/libvirt` 0.8.3 import does not reconstruct several
  `libvirt_domain` attributes; state was reconciled once by hand (local
  backup, out of tree). `plan` is green — do not recreate domains to
  "fix" it. Memory is ForceNew: resizing VMs recreates the domain
  definitions around the existing disks.
- Domain recreation re-randomizes MACs unless pinned; MACs are now
  pinned in configuration because netplan matches on MAC.
- The local KVM nodes have no registry egress, so every image there is
  side-loaded (tarball + `ctr import`, `Never` pull policy); see the per-area
  READMEs. The GCE nodes have full egress: the first install side-loads the
  application images, and the CD pipeline then pulls them from the GitLab
  Container Registry by digest.
- Monitoring storage is ephemeral; all-VM-shutdown persistence is an
  open advanced-component decision.
- Trust `terraform state list` + cluster reality over command output:
  killed background shells once left phantom state behind (resources
  tracked, nothing created). Diagnose with state-vs-cluster comparison,
  never by re-applying blindly.
- Verify image tarballs before distributing: one combined `docker save`
  referenced a missing blob, and layerless archives fail silently at
  `ctr import` time. Save per image and check blob completeness.

## Current status

**Status: live local platform; GCE track re-provisioned and green for the demo.**
Cluster, application, and monitoring are deployed and verified locally;
the same stack is currently provisioned on GCE (Madrid) with demo-check
21/21 and compliance 6 pass / 0 fail when last recorded (before inference
and CI/CD were added). The product endpoints, Qwen inference, the background
agent and the advanced component (CI/CD) are implemented and deployed on GCE.
