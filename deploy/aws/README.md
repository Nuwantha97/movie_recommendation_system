# Production deployment

GitHub Actions applies Terraform, builds the Vite frontend with the resulting API URL, and sends the backend release to EC2 through Systems Manager. It publishes the frontend to Cloudflare Pages after a public HTTPS search passes with the expected CORS header.

## Enable and trigger production

In **Settings → Secrets and variables → Actions → Variables**, set the **repository variable** `DEPLOY_ENABLED` to `true` when the account setup below is complete. Both triggers use this switch. A missing or disabled switch skips the release job before it accesses AWS or Cloudflare.

- **Automatic:** Push a change to a watched path on `main`, such as the frontend, backend, Terraform, or a DVC pointer.
- **Manual:** Open **Actions → Deploy production → Run workflow**, select `main`, and click **Run workflow**. This deploys the current `main` revision without requiring a new commit. The workflow file must already be on the repository's default branch.

## One-time account setup

1. For a new deployment, leave `TF_STATE_BUCKET` unset. Actions creates a private, versioned S3 bucket before Terraform starts and reuses it on later runs. The deployment role needs permission to deploy and describe the CloudFormation stack `movie-recs-state-<GitHub repository ID>` and to create the bucket and configure its versioning and public-access block. The default deployment region is `ap-southeast-2`.

   If production state already lives in S3, set `TF_STATE_BUCKET` to that existing bucket. If you previously applied Terraform locally, migrate the local state to your chosen bucket before enabling deployment. For an existing bucket, set the variable to the same name you use in the migration command below. The workflow expects the key `movie-recommendation/production.tfstate`. [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3)

   ```powershell
   $env:AWS_PROFILE = "dev1_nuwantha"
   terraform -chdir=terraform init -migrate-state -backend-config="bucket=YOUR_STATE_BUCKET" -backend-config="region=ap-southeast-2"
   terraform -chdir=terraform state list
   terraform -chdir=terraform plan
   ```

   If you already use a different remote state key or workspace, align the checked-in backend and workflow with that state first. Copy any local non-secret Terraform input overrides to the GitHub variable `TF_VARS_JSON`. Check that the plan recognizes your existing resources.

2. Configure AWS IAM federation for GitHub with audience `sts.amazonaws.com`. Give the deployment role a maximum session duration of **3 hours**. The trust policy template targets this repository's `production` environment. Restrict the environment to `main` in GitHub. [Trust policy template](github-oidc-policy.example.json)

   The runner role needs your Terraform provisioning permissions for the VPC, EC2, Elastic IP, RDS, release S3 bucket, instance profile and EC2 role declared in `terraform/`, including permission to pass that instance role. It also needs access to list the state bucket, read/write the state object, and read/write/delete the corresponding `.tflock` object. For application delivery, allow `s3:PutObject` for `movie-recs-release-*/releases/*`, `ssm:DescribeInstanceInformation`, `ssm:GetCommandInvocation`, and `ssm:SendCommand` for the account's backend instance and AWS's `AWS-RunShellScript` document. The EC2 instance reads the two runtime secrets with its own Terraform-managed role.

3. Create an AWS Secrets Manager secret named **`movie-recommendation/production`** in the deployment region. If you override `project_name`, use `<project_name>/production`. Use the default Secrets Manager encryption key or add the appropriate customer-managed KMS decrypt permission to EC2. Store the following JSON with actual values. Use a dedicated database login and keep its password stable between releases. When upgrading an existing deployment, use its existing login and password. RDS supplies and rotates its separate admin secret. [RDS password management](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html)

   ```json
   {
     "RDS_APP_USER": "app_ro",
     "RDS_APP_PASSWORD": "<strong application password>",
     "DAGSHUB_USER": "<DagsHub username>",
     "DAGSHUB_TOKEN": "<DagsHub token with read access to the DVC remote>",
     "GEMINI_API_KEY": "<Gemini API key>"
   }
   ```

   To manage those same five values from your computer, copy `deploy/aws/deploy.env.example` to `deploy.env` in the repository root and fill in the values in a local editor. Save as UTF-8, with one `KEY=value` per line. With AWS CLI signed into the deployment account, upload the file directly:

   ```powershell
   aws secretsmanager create-secret --region ap-southeast-2 --name movie-recommendation/production --secret-string file://deploy.env
   ```

   For an existing secret use `aws secretsmanager put-secret-value --region ap-southeast-2 --secret-id movie-recommendation/production --secret-string file://deploy.env`, then run the deployment. The local file is Git-ignored. Alternatively, a root-owned `/etc/movie-recs/deploy.env` on EC2 with permissions `600` takes priority over the application secret. A replacement EC2 instance needs its own copy when using that option. RDS continues to manage its admin password separately.

4. Set the following secrets and variables on the GitHub **production** environment. For an AWS-assigned HTTPS API address, leave `VITE_API_BASE` unset. Terraform creates a CloudFront distribution using the Elastic IP's public EC2 DNS name as its origin. The workflow reads the `cloudfront_api_base` Terraform output and builds it into the frontend. For this mode the deployment role needs permission to manage CloudFront distributions and read the CloudFront origin-facing EC2 managed prefix list. CloudFront usage can incur charges. For manual Terraform runs against the same state, pass `-var="use_cloudfront_api=true"` to match this workflow mode.

   To use a custom hostname, set `VITE_API_BASE`. Set `CLOUDFLARE_ZONE_ID` for automatic DNS in your Cloudflare zone, or point an external A record at Terraform's `ec2_public_ip` output. Caddy needs this DNS record to issue the custom hostname's HTTPS certificate. Switching modes on existing infrastructure may require reviewing and applying a plan separately if the workflow's deletion guard stops it.

   | Type | Name | Value |
   | --- | --- | --- |
   | Secret | `AWS_DEPLOY_ROLE_ARN` | GitHub OIDC role from step 2 |
   | Secret | `CLOUDFLARE_ACCOUNT_ID` | Account that owns the Pages project |
   | Secret | `CLOUDFLARE_API_TOKEN` | Pages Edit on that account, plus DNS Edit on the selected zone for automatic DNS |
   | Variable | `TF_STATE_BUCKET` | Optional override for an existing state bucket. Leave unset for automatic creation and reuse |
   | Variable | `VITE_API_BASE` | Optional custom HTTPS API URL, e.g. `https://api.example.com/api`. Omit for an AWS-assigned CloudFront URL |
   | Variable | `CLOUDFLARE_ZONE_ID` | Zone containing the API hostname, when managing its A record in Actions |
   | Variable | `AWS_REGION` | Defaults to `ap-southeast-2` |
   | Variable | `CLOUDFLARE_PAGES_PROJECT` | Defaults to `movie-recommendation-system`. Choose an available name for a new project |
   | Variable | `FRONTEND_ORIGIN` | Optional existing custom Pages origin, e.g. `https://movies.example.com`. The project's actual `pages.dev` origin is allowed automatically |
   | Variable | `TF_VARS_JSON` | Optional JSON object with non-secret input overrides from your existing plan |

   The workflow creates a missing Pages project with production branch `main`. For an existing Git-integrated project, turn off automatic Git builds to let this workflow control publication. Automatic API DNS uses a DNS-only A record pointing to the Elastic IP. A conflicting existing record must be reconciled by its owner. [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)

5. Before merging changes to DVC pointers, upload the matching objects to the repository's configured DagsHub remote from the machine containing the data.

   ```bash
   dvc push backend/artifacts/v1.dvc backend/chroma_data.dvc database/moviedb.sql.gz.dvc
   ```

## Release and recovery

The runner sends a checksum-verified source archive through a private S3 bucket. The EC2 instance installs its tools on first deployment and downloads the model artifacts, Chroma snapshot and compressed PostgreSQL dump directly from DagsHub. EC2 runs Caddy and one FastAPI worker. For the AWS-assigned URL, CloudFront serves HTTPS and forwards API requests over HTTP to port 80 on EC2. The security group restricts that port to CloudFront origin-facing addresses. With a custom domain, Caddy serves HTTPS directly and EC2 accepts public traffic on ports 80 and 443. RDS accepts PostgreSQL from the EC2 security group.

A changed database dump is imported into the inactive database (`moviedb_blue` or `moviedb_green`). The controller validates catalog rows, queries and grants before switching FastAPI. Changed model pointers get separate directories so the running release can finish using its current files. The database connection uses TLS hostname verification. The HTTP checks exercise FastAPI readiness, DB-backed movie and tag searches, the local Caddy origin, and the public HTTPS API.

During a backend switch the single EC2 service can be briefly unavailable. A failed health check attempts to restart the previous release with its matching image, model paths, and database. The release record in the RDS `postgres` database survives EC2 replacement. A fresh host rebuilds missing local assets. A failed first import can be retried. Pre-existing database slots with no matching release record require inspection. A failed Pages upload can be retried by rerunning the workflow.

The workflow refuses Terraform plans containing deletions or replacements. Review and apply an intentional replacement separately using the shared state. The default configuration provisions a 100 GiB EC2 volume, a static public IPv4 address, and private RDS with 20 GiB of storage that can grow to 100 GiB. These resources can incur charges.

For a failed release, open the SSM command ID printed by Actions. On EC2, `docker logs --tail 100 movies_backend` and `docker logs --tail 100 movies_proxy` show application and TLS startup errors. The deployment tests run locally with Python 3.11+ and `psycopg[binary]`.

```bash
python -m unittest discover -s deploy/aws -v
```
