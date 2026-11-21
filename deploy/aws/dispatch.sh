#!/usr/bin/env bash
set -euo pipefail
archive="$RUNNER_TEMP/source.tar.gz"
paths=(backend/app backend/scripts backend/Dockerfile backend/.dockerignore backend/requirements.txt
       backend/artifacts/v1.dvc backend/chroma_data.dvc database/moviedb.sql.gz.dvc
       .dvc/config .dvcignore compose.ec2.yml deploy/aws)
sha=$(git log -1 --format=%H HEAD -- "${paths[@]}")
git archive --format=tar.gz --output="$archive" "$sha" -- "${paths[@]}"
uri="s3://$RELEASE_BUCKET/releases/$sha.tar.gz"
aws s3 cp "$archive" "$uri" --only-show-errors

# SSM starts in /bin/sh. Quote each argument for that shell, including JSON.
site=${VITE_API_BASE#https://}
site=${site%/api}
# CloudFront terminates browser TLS and forwards the viewer's Host header.
if [[ "${USE_CLOUDFRONT_API:-false}" == true ]]; then site="http://$site"; fi
params=$(jq -n --arg sha "$sha" --arg uri "$uri" --arg digest "$(sha256sum "$archive" | cut -d' ' -f1)" \
  --arg region "$AWS_REGION" --arg host "$RDS_ENDPOINT" --arg port "$RDS_PORT" \
  --arg master "$RDS_MASTER_SECRET_ARN" --arg runtime "$RUNTIME_SECRET_NAME" \
  --arg site "$site" --arg origins "$CORS_ORIGINS" '
  ("/opt/movie-recs/releases/" + $sha) as $dir |
  {commands: [
    "set -eu", "umask 077", "cloud-init status --wait >/dev/null",
    "exec 9>/var/lock/movie-recs-deploy.lock", "flock -w 300 9",
    (["install","-d","-m","700",$dir] | @sh), (["cd",$dir] | @sh),
    (["aws","s3","cp",$uri,"release.tgz","--region",$region,"--only-show-errors"] | @sh),
    ("echo " + ([$digest + "  release.tgz"] | @sh) + " | sha256sum -c -"),
    "tar -xzf release.tgz",
    (["bash","deploy/aws/entrypoint.sh",$sha,$region,$host,$port,$master,$runtime,$site,$origins] | @sh)
  ],executionTimeout:["7200"]}')
for attempt in $(seq 1 90); do
  online=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$EC2_INSTANCE_ID" \
    --query 'InstanceInformationList[0].PingStatus' --output text)
  [[ "$online" == Online ]] && break
  sleep 10
done
[[ "$online" == Online ]] || { echo "EC2 did not register with SSM" >&2; exit 1; }
id=$(aws ssm send-command --instance-ids "$EC2_INSTANCE_ID" --document-name AWS-RunShellScript \
  --parameters "$params" --query Command.CommandId --output text)
echo "SSM command $id on $EC2_INSTANCE_ID"
for attempt in $(seq 1 510); do
  if result=$(aws ssm get-command-invocation --command-id "$id" --instance-id "$EC2_INSTANCE_ID"); then
    status=$(jq -r .Status <<<"$result")
    case "$status" in
      Success) jq -r .StandardOutputContent <<<"$result"; exit 0 ;;
      Pending|InProgress|Delayed) ;;
      *) jq -r '.StatusDetails,.StandardOutputContent,.StandardErrorContent' <<<"$result"; exit 1 ;;
    esac
  fi
  sleep 15
done
echo "Timed out waiting for SSM command $id" >&2
exit 1
