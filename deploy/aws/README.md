# AWS EC2 + private RDS deployment for movie_recommendation_system

Repository: https://github.com/dilminidasunika/movie_recommendation_system

**This is an additive patch, not a live deployment.** It was tailored to the public `main` branch inspected on 21 November 2026 and to your Terraform plan: **ap-southeast-2 (Sydney), m7i-flex.large (8 GiB EC2), db.t3.small (2 GiB RDS), PostgreSQL 18.6, Amazon Linux 2023**. It cannot guarantee AWS Free Plan permission, DagsHub availability, or sufficient application RAM. Review costs before creating billable resources.

## How this deployment works

- Your **original** `docker-compose.yml`, `docker-compose.override.yml`, `deploy/bootstrap.sh`, and main `README.md` remain unchanged. They are for your existing local/PostgreSQL-container workflow.
- `compose.ec2.yml` runs **FastAPI + Caddy** on public EC2. It has **no local PostgreSQL container**. FastAPI uses a `postgresql://` URL with TLS certificate verification to the private RDS endpoint.
- The DVC remote at `.dvc/config` is `origin` (DagsHub HTTPS). The script downloads the SQL backup, `backend/artifacts/v1`, and `backend/chroma_data`. Model artifacts are roughly 3.1 GB; Chroma data roughly 3.9 GB, excluding cache and build layers. A **60 GiB encrypted gp3** EC2 root volume is a starting point; monitor actual space.
- `compose.ec2.yml` deliberately **overrides** the backend Dockerfile startup script to run one Uvicorn worker, avoiding an expensive `scripts.init_chroma` rebuild. It requires the checked-out, valid `backend/chroma_data/chroma.sqlite3` collection to be usable on Linux. If the Chroma data is incompatible, you must rebuild the collection as a separate, planned task; this is not tested remotely.
- RDS is one **Single-AZ instance** containing *two logical databases*: `moviedb_blue` and `moviedb_green`. On DB-dump changes the inactive slot is replaced and validated before FastAPI is switched over. The previous slot remains available for rollback. One instance still represents one failure domain; this is **not zero-downtime infrastructure** or a replacement for RDS backups.
- GitHub-hosted Actions authenticates via AWS **OIDC** and sends the deploy command using **SSM Run Command** to EC2. Credentials for RDS and DagsHub stay on EC2 in a root-only file, not in GitHub Actions.

## Patch file placement

Extract this ZIP **over the repository root** (`D:\Projects\movie_recommendation_system` on your machine), preserving folders. The patch contains:

```
.github/workflows/aws-rds-ec2-sync.yml
compose.ec2.yml
deploy/aws/README.md
deploy/aws/bootstrap-amazon-linux-2023.sh
deploy/aws/deploy.env.example
deploy/aws/entrypoint.sh
deploy/aws/sync.py
deploy/aws/pgdump_filter.py
deploy/aws/test_pgdump_filter.py
deploy/aws/test_deployment_configuration.py
deploy/aws/github-oidc-policy.example.json
deploy/aws/github-ssm-policy.example.json
deploy/aws/terraform-ec2-web-rules.tf.example
```

**Do not overwrite your existing root `README.md` or existing Terraform resource files.** The Terraform example is not an independently executable Terraform project; it depends on your already-configured `aws_security_group.ec2` and must be copied into that *same* Terraform directory.

## Step 1. Update and review your existing Terraform

Your last `terraform plan` showed five new resources: EC2, RDS, IAM role, instance profile and policy attachment. Configure these existing resources in your local `terraform/` directory:

| Resource | Required setup |
|---|---|
| `aws_instance.backend` | `m7i-flex.large`, Amazon Linux 2023 x86_64, EC2 public subnet, EC2 security group, SSM instance profile, `metadata_options.http_tokens = "required"` |
| `root_block_device` | `volume_size = 60`, `volume_type = "gp3"`, `encrypted = true` (30 GiB from the previous plan may be tight due to DVC and Docker layers) |
| `aws_db_instance.postgres` | `db.t3.small`, PostgreSQL `18.6`, `storage_type = "gp2"`, `allocated_storage = 20`, encrypted, `publicly_accessible = false`, `multi_az = false`, `manage_master_user_password = true` |
| DB network | Existing private subnet group and existing RDS SG admitting `5432` **from EC2 SG only** |
| EC2 network | Existing public subnet + internet gateway; no inbound `22`, `5432`, or `8000` |

To serve a browser on the EC2 public IP in a **temporary restricted HTTP test**, copy `deploy/aws/terraform-ec2-web-rules.tf.example` into your current local Terraform directory as `ec2-web.tf`. Prefer setting `movie_web_allowed_cidr` to your **own public IP `/32`** in `terraform.tfvars`. For general public access, use a domain, valid HTTPS, and open port 443 too. HTTP sends movie searches without TLS; do not use it for sensitive user data. Avoid opening port 8000. If a public website is not necessary, skip all web ingress rules and use SSM/local checks.

In Windows CMD:

```cmd
cd /d D:\Projects\movie_recommendation_system\terraform
terraform fmt
terraform validate
terraform plan
```

**Read the plan and AWS cost estimate before running `terraform apply`.** Your new-account Free Plan and remaining AWS credits may restrict or charge for these instance types. `plan` does *not* guarantee permission to create them. If accepted, `terraform apply` and obtain:

```cmd
terraform output
terraform output -raw ec2_instance_id
terraform output -raw ec2_public_ip
terraform output -raw rds_endpoint
terraform output -raw rds_master_secret_arn
```

RDS creation may require substantial time. Once available, fetch the autogenerated RDS master password using Secrets Manager **on your own computer** (do not paste it into chat, Git, or CI logs):

```cmd
aws secretsmanager get-secret-value --secret-id YOUR_RDS_MASTER_SECRET_ARN --region ap-southeast-2 --profile dev1_nuwantha --query SecretString --output text
```

This returns JSON containing a username and password. The username should match `db_username = "movieadmin"` if you used the previous Terraform example. Store the password only in `/etc/movie-recs/deploy.env` on EC2. Note that `Secrets Manager` may cost extra.

## Step 2. Connect to EC2 and bootstrap Amazon Linux 2023

Use the **AWS Console > EC2 > select instance > Connect > Session Manager** after checking that the SSM agent is online. Your existing EC2 IAM instance profile contains `AmazonSSMManagedInstanceCore`. A public subnet with HTTPS outbound traffic lets SSM work without a NAT Gateway. Session Manager avoids exposing SSH port 22.

On the EC2 shell:

```bash
sudo dnf install -y git
sudo mkdir -p /opt/movie-recs
sudo git clone https://github.com/dilminidasunika/movie_recommendation_system.git \
  /opt/movie-recs/movie_recommendation_system
cd /opt/movie-recs/movie_recommendation_system
sudo bash deploy/aws/bootstrap-amazon-linux-2023.sh
sudo docker compose version
```

The bootstrap installs Docker, Git, Python, a dedicated Python virtualenv containing DVC/psycopg/python-dotenv, the Docker Compose plugin (if missing), and the official AWS RDS global CA bundle. It copies a **placeholder-only** environment file to `/etc/movie-recs/deploy.env`; it never inserts actual tokens itself. It pins a Docker Compose release for repeatability; for a long-running deployment, review the upstream release/checksum and upgrade deliberately.

**Important**: the bootstrap script is in your ZIP. Commit and push the patch to GitHub **before cloning the repo on EC2**.

## Step 3. Configure EC2-only secrets

Edit on EC2:

```bash
sudo vi /etc/movie-recs/deploy.env
```

Set all placeholders:

| Setting | Where you obtain it |
|---|---|
| `RDS_HOST` | `terraform output -raw rds_endpoint` (hostname only, no port) |
| `RDS_PORT` | `5432` |
| `RDS_ADMIN_USER` | `movieadmin` if you used the previous Terraform settings |
| `RDS_ADMIN_PASSWORD` | The **password** field of the Secrets Manager JSON |
| `RDS_APP_USER` | `app_ro` (new role created automatically, not the DB master) |
| `RDS_APP_PASSWORD` | A separate, strong password that you generate |
| `DAGSHUB_USER`, `DAGSHUB_TOKEN` | Your own DagsHub credentials for the existing HTTPS DVC remote |
| `GEMINI_API_KEY` | Your application's existing Gemini API key |
| `SITE_ADDRESS` | `:80` for restricted HTTP testing, or a DNS hostname for public HTTPS |
| `ALLOWED_HOSTS`, `CORS_ORIGINS` | JSON-string arrays of the actual EC2 IP/domain and browser origin; replace example placeholders |
| `FORWARDED_ALLOW_IPS` | Proxy IP/subnet from Docker network if you need client-IP forwarding; never `*` |

For example, for a private temporary test on a permitted EC2 public IP:

```
SITE_ADDRESS=:80
ALLOWED_HOSTS=["localhost","127.0.0.1","YOUR_EC2_PUBLIC_IP"]
CORS_ORIGINS=["http://YOUR_EC2_PUBLIC_IP"]
```

Do not include `http://` inside the `ALLOWED_HOSTS` values. Replace `YOUR_EC2_PUBLIC_IP` with the actual value; EC2 public IP may change after stopping and starting the instance.

Secure the file:

```bash
sudo chown root:root /etc/movie-recs/deploy.env
sudo chmod 600 /etc/movie-recs/deploy.env
sudo test -s /etc/movie-recs/global-bundle.pem
sudo df -h /
```

No AWS access keys, RDS passwords, Gemini keys, or DagsHub tokens belong in the GitHub repository or Terraform variables.

## Step 4. First deployment (manual)

On EC2, ensure RDS is available and your EC2 security group can reach RDS security group port 5432. Then run:

```bash
cd /opt/movie-recs/movie_recommendation_system
sudo ./deploy/aws/entrypoint.sh "$(git rev-parse HEAD)"
sudo docker compose -f compose.ec2.yml ps
sudo docker logs --tail 100 movies_backend
sudo cat /var/lib/movie-recs/deploy-state.json
```

Expected sequence: DVC downloads the three tracked resources; the controller checks the gzip dump; creates `moviedb_blue`; imports the SQL with PostgreSQL 18 client; validates table counts, `pg_trgm`, and sample SQL; sets up the read-only role; builds frontend/backend; switches FastAPI to blue; and checks health plus `/api/movies/search` and `/api/tags/search?types=genres`. If all succeed, the state file records blue as active.

For a temporary HTTP test after allowing security-group inbound TCP 80:

```bash
curl -i http://127.0.0.1/
curl -i 'http://127.0.0.1/api/movies/search?q=matrix&limit=1'
```

**Partial initial import caution**: if the first import fails, `moviedb_blue` may remain partially created while there is no deployment state file. The script refuses to delete any pre-existing slot without a state file. Inspect it carefully, then manually drop that **failed/staged** database only if you are sure it contains no valuable data, and rerun. Do not delete `/var/lib/movie-recs/deploy-state.json` to bypass safety checks.

**Data compatibility**: If your trusted SQL backup contains `CREATE DATABASE`, `\\connect`, ownership commands not handled by the filter, or unsupported extensions, restore fails deliberately. For future backups, prefer generating a database-local plain SQL dump with `pg_dump --no-owner --no-acl` and `gzip` before pushing its `.dvc` to DagsHub.

## Step 5. Enable optional GitHub Actions automation

Only after the first successful EC2 deployment:

1. In AWS IAM add GitHub's OIDC provider `https://token.actions.githubusercontent.com` with audience `sts.amazonaws.com` if needed.
2. Create an IAM role such as `movie-github-ssm-deployer`. Use the **trust policy** `deploy/aws/github-oidc-policy.example.json` after replacing `ACCOUNT_ID`. The role trust is bound to this repository's GitHub `production` environment.
3. Attach an inline permissions policy from `deploy/aws/github-ssm-policy.example.json`, replacing `REGION` with `ap-southeast-2`, `ACCOUNT_ID` with yours, and `EC2_INSTANCE_ID` with `terraform output -raw ec2_instance_id`.
4. In GitHub, create a **production** Environment restricted to the `main` branch. Consider required reviewers for deployments.
5. In **GitHub repository > Settings > Secrets and variables > Actions**, set:
   - **Secret** `AWS_DEPLOY_ROLE_ARN` = ARN of the GitHub OIDC deployment role.
   - **Variable** `AWS_REGION` = `ap-southeast-2`.
   - **Variable** `EC2_INSTANCE_ID` = EC2 instance ID from Terraform.
   - **Variable** `DEPLOY_ENABLED` = `true` only when the first deployment is healthy.
6. In GitHub Actions run **Temporary EC2 and private-RDS blue-green deploy** manually. Then push future backend/frontend/DB `.dvc` commits to `main` as usual. Make sure DVC data is successfully **pushed to DagsHub before** committing/pushing the updated `.dvc` file.

If your AWS Free Plan denies OIDC provider/role/SSM policy creation, do not enable the workflow. Manual SSM deployment can continue once the appropriate access exists.

## How blue-green updates work, and limitations

On a database dump change, the script downloads the updated backup and recreates **only the inactive logical database** (`moviedb_blue` or `moviedb_green`). After SQL/schema checks, it switches a single FastAPI container to the new DB. If the app fails readiness checks, it attempts to restore the previous backend image and active DB. The successful deployment state advances only after validation. This causes a **brief interruption** and rollback is **best effort**, not guaranteed through EC2/RDS outages.

Backend/frontend-only commits rebuild the application without replacing the DB. Changes to `backend/artifacts/v1.dvc` or `backend/chroma_data.dvc` are **refused automatically** after the first deployment; those require a coordinated model release and a separate migration plan. Two DB slots on one 2 GiB RDS instance consume more storage and CPU: measure `FreeStorageSpace`, CPU, connections, and restore time.

The controller does **not** test `/api/recommend` end-to-end. Ensure model readiness and representative recommendation responses manually before showing the site to users. A single FastAPI worker is required by the in-process caches and Chroma integration.

For diagnostics:

```bash
sudo docker compose -f compose.ec2.yml ps
sudo docker logs --tail 150 movies_backend
sudo docker logs --tail 100 movies_proxy
sudo cat /var/lib/movie-recs/deploy-state.json
```

## Cost and safe shutdown

- EC2 `m7i-flex.large` (8 GiB) and RDS `db.t3.small` (2 GiB) may be **billable** even if an AWS `free-tier-eligible` query lists other shapes. Your account uses temporary Free Plan credits; verify actual launch permissions and pricing in Sydney.
- One public IPv4 address, 60 GiB EBS, 20 GiB gp2 RDS, storage for backups/Secrets Manager, and data transfer can add charges. Set AWS Budgets alerts before starting.
- Avoid NAT Gateways, load balancers, extra RDS instances and Multi-AZ for this short-lived proof of concept.
- Stopping EC2 saves compute charges but not EBS; the public IPv4 may change. Stopping RDS is temporary and the service may automatically restart it after seven days. Cleanup is a separate deliberate operation: protect/backup data, disable RDS deletion protection if deleting, and account for final snapshots that can continue to accrue costs. Don't run `terraform destroy` until you understand the state and retention consequences.

## Local tests (do not contact AWS)

From the repository root:

```bash
python -m unittest discover -s deploy/aws -p 'test_*.py' -v
python -m compileall -q deploy/aws
bash -n deploy/aws/entrypoint.sh deploy/aws/bootstrap-amazon-linux-2023.sh
```

If Docker Compose is installed, validate interpolation *using dummy environment variables* (this only parses config; no containers started):

```bash
DATABASE_URL='postgresql://user:dummy@db.example:5432/moviedb_blue' \
GEMINI_API_KEY='dummy' ALLOWED_HOSTS='["localhost"]' \
CORS_ORIGINS='["http://localhost"]' \
docker compose -f compose.ec2.yml config --quiet
```

**Verification boundary:** The patch was Python syntax-checked, tested with unit tests and parsed as YAML. It was **not** run against your live EC2, private RDS, DVC cache, or AWS credentials, so call it deployment-ready *configuration*, not a proven live deployment.
