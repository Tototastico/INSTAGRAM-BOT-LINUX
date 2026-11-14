#!/usr/bin/env bash
# Read-only inspection. Never print credentials or Authorization headers.
set -euo pipefail
IP="${1:-88.198.136.72}"
echo "Nginx listeners and matching server names:"
sudo nginx -T 2>&1 | grep -En 'listen (80|443)|server_name|auth_basic|auth_basic_user_file|return 30[1278]|proxy_pass|ssl_certificate' || true
echo "TLS certificate for ${IP}:"
echo | openssl s_client -connect "${IP}:443" -servername "${IP}" 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName || true
for scheme in http https; do
  for path in / /api/health /api/accounts; do
    echo "${scheme}://${IP}${path} without credentials:"
    curl --max-time 10 -sS -D - -o /dev/null "${scheme}://${IP}${path}" | grep -Ei '^(HTTP/|www-authenticate:|location:|server:)' || true
  done
done
read -r -p 'Basic Auth username (password is requested securely by curl): ' username
for path in / /api/health /api/accounts; do
  echo "https://${IP}${path} with Basic Auth:"
  curl --max-time 10 -sS -u "$username" -D - -o /dev/null "https://${IP}${path}" | grep -Ei '^(HTTP/|www-authenticate:|location:|server:)' || true
done
echo 'Compare these status lines with Chrome mobile Network inspection; do not share passwords or Authorization headers.'
