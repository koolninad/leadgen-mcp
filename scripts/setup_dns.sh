#!/bin/bash
# Setup DNS records for all domains via Cloudflare Wrangler
# Usage: CLOUDFLARE_API_TOKEN=xxx ./setup_dns.sh
#
# Each domain needs:
#   MX record → mail server
#   TXT record → SPF
#   TXT record → DMARC
#   CNAME record → DKIM (get from Stalwart)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOMAINS_FILE="$SCRIPT_DIR/domains.txt"

# Mail server hostname (your Stalwart/Nubo server)
MAIL_SERVER="mail.nubo.email"
MAIL_SERVER_IP=""  # Set if you want A record instead of CNAME

# SPF record - authorize your mail server
SPF_RECORD="v=spf1 mx a include:nubo.email ~all"

# DMARC record
DMARC_RECORD="v=DMARC1; p=none; rua=mailto:dmarc@nubo.email; ruf=mailto:dmarc@nubo.email; fo=1"

# Check wrangler
if ! command -v wrangler &>/dev/null; then
    echo "Installing wrangler..."
    npm install -g wrangler 2>/dev/null || npx wrangler --version
fi

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
    echo "ERROR: Set CLOUDFLARE_API_TOKEN environment variable"
    echo "  Get one at: https://dash.cloudflare.com/profile/api-tokens"
    echo "  Needs: Zone:DNS:Edit permission for all zones"
    exit 1
fi

export CLOUDFLARE_API_TOKEN

echo "=== Setting up DNS records ==="

# Function to get zone ID for a domain
get_zone_id() {
    local domain="$1"
    # For subdomains like tez.ind.in, we need the root zone
    local root_domain
    # Simple extraction: take last 2 parts (or 3 for .co.uk, .ind.in type)
    local parts
    IFS='.' read -ra parts <<< "$domain"
    local num_parts=${#parts[@]}

    if [ $num_parts -ge 3 ]; then
        # Check if it's a known ccSLD pattern (ind.in, co.uk, etc.)
        local sld="${parts[$((num_parts-2))]}.${parts[$((num_parts-1))]}"
        case "$sld" in
            ind.in|co.uk|co.in|org.in|net.in|ac.in|co.jp|co.nz)
                root_domain="${parts[$((num_parts-3))]}.$sld"
                ;;
            *)
                root_domain="${parts[$((num_parts-2))]}.${parts[$((num_parts-1))]}"
                ;;
        esac
    else
        root_domain="$domain"
    fi

    curl -s -X GET "https://api.cloudflare.com/client/v4/zones?name=$root_domain" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('result', [])
if results:
    print(results[0]['id'])
else:
    print('')
"
}

# Function to create DNS record
create_record() {
    local zone_id="$1"
    local type="$2"
    local name="$3"
    local content="$4"
    local priority="${5:-}"

    local payload="{\"type\":\"$type\",\"name\":\"$name\",\"content\":\"$content\",\"ttl\":3600"
    if [ -n "$priority" ]; then
        payload="$payload,\"priority\":$priority"
    fi
    payload="$payload}"

    local result
    result=$(curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$zone_id/dns_records" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json" \
        --data "$payload")

    if echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('success') else 1)" 2>/dev/null; then
        echo "    OK: $type $name -> $content"
    else
        local err
        err=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); errs=d.get('errors',[]); print(errs[0].get('message','unknown') if errs else 'unknown')" 2>/dev/null)
        echo "    SKIP: $type $name ($err)"
    fi
}

TOTAL=0
SUCCESS=0

while IFS= read -r domain; do
    [ -z "$domain" ] && continue

    echo ""
    echo "--- $domain ---"

    ZONE_ID=$(get_zone_id "$domain")
    if [ -z "$ZONE_ID" ]; then
        echo "  WARNING: Zone not found in Cloudflare for $domain — skipping"
        continue
    fi

    echo "  Zone ID: ${ZONE_ID:0:8}..."

    # MX record
    create_record "$ZONE_ID" "MX" "$domain" "$MAIL_SERVER" 10

    # SPF record
    create_record "$ZONE_ID" "TXT" "$domain" "$SPF_RECORD"

    # DMARC record
    create_record "$ZONE_ID" "TXT" "_dmarc.$domain" "$DMARC_RECORD"

    # Mail A/CNAME record (for mail.$domain)
    if [ -n "$MAIL_SERVER_IP" ]; then
        create_record "$ZONE_ID" "A" "mail.$domain" "$MAIL_SERVER_IP"
    fi

    TOTAL=$((TOTAL + 1))
    SUCCESS=$((SUCCESS + 1))

done < "$DOMAINS_FILE"

echo ""
echo "=== DNS Setup Complete ==="
echo "Domains processed: $TOTAL"
echo ""
echo "IMPORTANT: DKIM records need to be added manually."
echo "Get DKIM public keys from Stalwart for each domain:"
echo "  kubectl exec -n <ns> <pod> -- stalwart-cli domain dkim <domain>"
echo "Then add TXT record: default._domainkey.<domain> -> <dkim_public_key>"
