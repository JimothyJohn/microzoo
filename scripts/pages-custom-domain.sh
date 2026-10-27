#!/usr/bin/env bash
# Set microzoo.advin.io as the GitHub Pages custom domain and enforce HTTPS once the
# certificate is issued. Needs: gh authenticated as the repo admin; the DNS CNAME in place
# (scripts/dns-microzoo-advin.sh) and docs/CNAME on master (dev -> master is Nick's merge).
# Idempotent: re-run until it prints "ok". Run here as `! ./scripts/pages-custom-domain.sh`.
set -euo pipefail

REPO="${REPO:-JimothyJohn/microzoo}"
HOST="${HOST:-microzoo.advin.io}"

if ! dig +short "$HOST" CNAME | grep -q 'github.io'; then
  echo "DNS first: $HOST has no CNAME to github.io yet (scripts/dns-microzoo-advin.sh)" >&2; exit 1
fi

CNAME=$(gh api "repos/$REPO/pages" --jq '.cname // ""')
if [[ "$CNAME" != "$HOST" ]]; then
  echo "setting custom domain $HOST"
  gh api -X PUT "repos/$REPO/pages" -f cname="$HOST" >/dev/null
fi

# GitHub provisions the certificate asynchronously; HTTPS can only be enforced after that.
for _ in $(seq 1 30); do
  STATE=$(gh api "repos/$REPO/pages" --jq '[.cname, (.https_enforced|tostring), (.protected_domain_state // "null"), .status] | join(" ")')
  read -r cname https protected status <<<"$STATE"
  echo "cname=$cname https_enforced=$https domain_state=$protected build=$status"
  if [[ "$cname" == "$HOST" && "$https" == "true" ]]; then
    echo "ok: https://$HOST"; curl -sS -o /dev/null -w 'GET https://%{url_effective} -> %{http_code}\n' "https://$HOST/" || true; exit 0
  fi
  if [[ "$cname" == "$HOST" && "$https" != "true" ]]; then
    if gh api -X PUT "repos/$REPO/pages" -f https_enforced=true >/dev/null 2>&1; then
      echo "https enforced"; continue
    fi
    echo "certificate not ready yet; retrying in 60 s"
  fi
  sleep 60
done
echo "gave up after 30 min: check https://github.com/$REPO/settings/pages" >&2
exit 1
