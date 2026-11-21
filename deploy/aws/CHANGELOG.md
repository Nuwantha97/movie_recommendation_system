# Integration corrections to the uploaded ZIP

Updated for `dilminidasunika/movie_recommendation_system` and the existing Sydney Terraform plan:

- Moved ZIP's AWS-specific `README.md` to `deploy/aws/README.md`, avoiding overwriting the repository's root README.
- Updated AWS Region examples from Mumbai to Sydney and DB administrator username to `movieadmin`.
- Added `bootstrap-amazon-linux-2023.sh` to install Docker, Docker Compose (when missing), a Python deploy venv, DVC HTTP support, and the AWS RDS CA bundle on the EC2 Amazon Linux 2023 AMI.
- Fixed `entrypoint.sh` PATH: `dvc` installed in `/opt/movie-recs/venv/bin` is now available to `sync.py` subprocesses.
- Fixed actual tag-search URL: `types=genres` instead of the invalid `types=genre`.
- Disabled the Dockerfile's automatic Chroma rebuild **for this AWS Compose deployment only**, using the already downloaded DVC ChromaDB assets.
- Added a DVC checkout preflight confirming `backend/chroma_data/chroma.sqlite3` exists; set `cache.type=copy` to avoid corrupting cached Chroma SQLite files with live writes.
- Added backend `scripts/**` and model/Chroma `.dvc` files to GitHub Actions trigger paths; model/Chroma hash changes still fail-safe in the controller.
- Added an optional `terraform-ec2-web-rules.tf.example` for the existing EC2 security group (no inbound 8000/5432).
- Added deployment configuration tests; retained existing streaming SQL dump filter tests.

**Limitations**: Not deployed to your AWS account, not end-to-end tested against a real DagsHub pull or PostgreSQL import, not verified that prebuilt Chroma files are Linux-compatible, and not guaranteed to fit within 8 GiB RAM or Free Plan credits. The AWS GitHub Actions OIDC role and Terraform resources still require setup and a reviewed `terraform apply`.
