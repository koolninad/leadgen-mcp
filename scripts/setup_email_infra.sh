#!/bin/bash
# Setup email infrastructure: create domains + accounts in Stalwart via k3s
# Usage: ./setup_email_infra.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOMAINS_FILE="$SCRIPT_DIR/domains.txt"

# Email accounts to create per domain (5 per domain)
ACCOUNTS=("sales" "info" "hello" "team" "support")
DEFAULT_PASSWORD="Nubo@2026!Secure"

# Find Stalwart pod
echo "=== Finding Stalwart pod ==="
STALWART_POD=$(kubectl get pods --all-namespaces -l app=stalwart -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || \
               kubectl get pods --all-namespaces | grep -i stalwart | head -1 | awk '{print $2}')
STALWART_NS=$(kubectl get pods --all-namespaces | grep -i stalwart | head -1 | awk '{print $1}')

if [ -z "$STALWART_POD" ]; then
    echo "ERROR: Stalwart pod not found. Trying to find it..."
    kubectl get pods --all-namespaces | grep -iE "stalwart|mail|smtp"
    exit 1
fi

echo "Pod: $STALWART_POD (namespace: $STALWART_NS)"

# Function to run stalwart-cli
stalwart_cli() {
    kubectl exec -n "$STALWART_NS" "$STALWART_POD" -- stalwart-cli "$@" 2>/dev/null || \
    kubectl exec -n "$STALWART_NS" "$STALWART_POD" -- /usr/local/bin/stalwart-cli "$@" 2>/dev/null || \
    kubectl exec -n "$STALWART_NS" "$STALWART_POD" -- /opt/stalwart-mail/bin/stalwart-cli "$@" 2>/dev/null
}

echo ""
echo "=== Creating domains and accounts ==="
TOTAL_DOMAINS=0
TOTAL_ACCOUNTS=0

while IFS= read -r domain; do
    # Skip empty lines
    [ -z "$domain" ] && continue

    echo ""
    echo "--- Domain: $domain ---"

    # Create domain
    stalwart_cli domain create "$domain" 2>/dev/null && echo "  Created domain: $domain" || echo "  Domain exists: $domain"
    TOTAL_DOMAINS=$((TOTAL_DOMAINS + 1))

    # Create email accounts
    for acct in "${ACCOUNTS[@]}"; do
        email="${acct}@${domain}"
        stalwart_cli account create "$email" "$DEFAULT_PASSWORD" 2>/dev/null && \
            echo "  Created: $email" || echo "  Exists: $email"
        TOTAL_ACCOUNTS=$((TOTAL_ACCOUNTS + 1))
    done

done < "$DOMAINS_FILE"

echo ""
echo "=== Summary ==="
echo "Domains: $TOTAL_DOMAINS"
echo "Accounts: $TOTAL_ACCOUNTS"
echo "Password: $DEFAULT_PASSWORD"
echo ""
echo "Next: Run setup_dns.sh to configure Cloudflare DNS records"
