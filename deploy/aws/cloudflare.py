"""Prepare the Direct Upload project and (optionally) its API's DNS-only record."""
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def api(path, method="GET", body=None, missing_ok=False):
    request = Request("https://api.cloudflare.com/client/v4/" + path, method=method,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"],
                               "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise RuntimeError(f"Cloudflare {method} {path}: {error.code} {error.read().decode()}") from None
    if not result["success"]:
        raise RuntimeError(f"Cloudflare request failed: {result['errors']}")
    return result["result"]


def main():
    projects = f"accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/pages/projects"
    name = os.environ["PAGES_PROJECT"]
    project = api(f"{projects}/{name}", missing_ok=True)
    if project is None:
        project = api(projects, "POST", {"name": name, "production_branch": "main"})
    if project["production_branch"] != "main":
        raise ValueError("Set the Pages project's production branch to main")
    pages = "https://" + project["subdomain"]
    origin = os.environ.get("FRONTEND_ORIGIN") or pages
    url = urlsplit(origin)
    if url.scheme != "https" or not url.hostname or origin != "https://" + url.hostname:
        raise ValueError("FRONTEND_ORIGIN must be a bare HTTPS origin")
    with open(os.environ["GITHUB_ENV"], "a") as output:
        print(f"FRONTEND_ORIGIN={origin}", file=output)
        print("CORS_ORIGINS=" + json.dumps(sorted({origin, pages})), file=output)
    zone = os.environ.get("CLOUDFLARE_ZONE_ID")
    if zone:
        name = urlsplit(os.environ["VITE_API_BASE"]).hostname
        ip = os.environ["EC2_PUBLIC_IP"]
        records = f"zones/{zone}/dns_records"
        existing = api(records + "?" + urlencode({"name": name, "type": "A"}))
        marker = "Managed by movie-recommendation production deployment"
        record = {"name": name, "type": "A", "content": ip, "ttl": 1,
                  "proxied": False, "comment": marker}
        if not existing:
            api(records, "POST", record)
        elif len(existing) == 1 and existing[0]["content"] == ip and not existing[0]["proxied"]:
            return
        elif len(existing) == 1 and existing[0].get("comment") == marker:
            api(records + "/" + existing[0]["id"], "PUT", record)
        else:
            raise ValueError(f"Existing DNS for {name} conflicts with API address {ip}")


if __name__ == "__main__":
    main()
