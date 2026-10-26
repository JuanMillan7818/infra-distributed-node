#!/bin/bash
# User data para EC2 (Ubuntu 24.04). Se ejecuta una sola vez, como root, en el primer arranque.
# Log: /var/log/cloud-init-output.log
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg git openssl htop unzip

# Docker Engine + plugin Compose (script oficial)
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sh /tmp/get-docker.sh
usermod -aG docker ubuntu
systemctl enable --now docker

# Rotación de logs de contenedores: evita que llenen el disco de 30 GB
cat >/etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
systemctl restart docker

# Swap de 2 GB: colchón de memoria para la instancia de 2 GB RAM
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -w vm.swappiness=10
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf

timedatectl set-timezone America/Bogota
