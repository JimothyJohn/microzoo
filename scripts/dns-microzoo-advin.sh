#!/usr/bin/env bash
# Point microzoo.advin.io at GitHub Pages (Route 53 CNAME -> jimothyjohn.github.io).
# Needs: aws CLI with write access to the advin.io hosted zone (Z039212425BG1MHVPYWDN).
# Idempotent: UPSERT, then waits for the change and checks the record resolves.
# Run here as `! ./scripts/dns-microzoo-advin.sh`. Pages still needs docs/CNAME on master
# and the custom domain set (scripts/pages-custom-domain.sh).
set -euo pipefail

HOST="${HOST:-microzoo.advin.io}"
TARGET="${TARGET:-jimothyjohn.github.io}"
ZONE_NAME="advin.io."

ZONE_ID=$(aws route53 list-hosted-zones-by-name --dns-name "$ZONE_NAME" --max-items 1 \
  --query "HostedZones[?Name=='${ZONE_NAME}'].Id | [0]" --output text)
if [[ -z "$ZONE_ID" || "$ZONE_ID" == "None" ]]; then
  echo "no hosted zone for $ZONE_NAME in this account" >&2; exit 1
fi
echo "zone $ZONE_ID"

CURRENT=$(aws route53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
  --query "ResourceRecordSets[?Name=='${HOST}.' && Type=='CNAME'].ResourceRecords[0].Value | [0]" --output text)
if [[ "$CURRENT" == "$TARGET" ]]; then
  echo "already set: $HOST CNAME $TARGET"
else
  BATCH=$(printf '{"Comment":"microzoo GitHub Pages","Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":"%s","Type":"CNAME","TTL":300,"ResourceRecords":[{"Value":"%s"}]}}]}' "$HOST" "$TARGET")
  CHANGE_ID=$(aws route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" --change-batch "$BATCH" \
    --query 'ChangeInfo.Id' --output text)
  echo "submitted $CHANGE_ID, waiting for INSYNC"
  aws route53 wait resource-record-sets-changed --id "$CHANGE_ID"
fi

# Verify: the zone's own name server first (fresh, ignores caches), then the system resolver.
# Some networks block direct queries to outside name servers, so a timeout there is not fatal;
# dig's failure must not kill the script silently under `set -e -o pipefail`.
NS=$(aws route53 get-hosted-zone --id "$ZONE_ID" --query 'DelegationSet.NameServers[0]' --output text)
for via in "$NS" ""; do
  ANSWER=$(dig +short +time=3 +tries=1 ${via:+@"$via"} "$HOST" CNAME 2>/dev/null | sed 's/\.$//' || true)
  label=${via:-system resolver}
  if [[ "$ANSWER" == "$TARGET" ]]; then
    echo "ok: $HOST CNAME $TARGET (via $label)"; exit 0
  fi
  echo "no answer for $HOST at $label (got '${ANSWER}')" >&2
done
echo "verification failed: $HOST does not resolve to $TARGET yet" >&2
exit 1
