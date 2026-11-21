#!/bin/bash
set -euxo pipefail

dnf update -y
dnf install -y docker git

systemctl enable --now docker

mkdir -p /opt/movie-recommendation
chmod 755 /opt/movie-recommendation
