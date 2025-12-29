# Unified AuthBridge Demo

This demo combines the **Client Registration** and **AuthProxy** components to demonstrate a complete end-to-end authentication flow with SPIFFE/SPIRE integration.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                           CALLER POD                                   │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Init Container: proxy-init (iptables setup)                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Containers                                 │   │
│  │  ┌──────────────┐  ┌─────────────────┐  ┌────────────────────┐  │   │
│  │  │   Caller     │  │  SPIFFE Helper  │  │    AuthProxy +     │  │   │
│  │  │  (netshoot)  │  │  (provides      │  │    Envoy + Go Proc │  │   │
│  │  │              │  │   SPIFFE creds) │  │  (token exchange)  │  │   │
│  │  └──────┬───────┘  └─────────────────┘  └──────────┬─────────┘  │   │
│  │                                                                 │   │
│  │  ┌───────────────────────────────────────────────────────────┐  │   │
│  │  │ client-registration (registers with Keycloak using SPIFFE)│  │   │
│  │  └───────────────────────────────────────────────────────────┘  │   │
│  └─────────┼───────────────────────────────────────────┼───────────┘   │
│            │ HTTP request with token                   │               │
│            └───────────────────────────────────────────┘               │
│                              │                                         │
└──────────────────────────────┼─────────────────────────────────────────┘
                               │ Token exchanged for demoapp audience
                               ▼
                    ┌─────────────────────┐
                    │    DEMO APP POD     │
                    │   (Target Server)   │
                    │                     │
                    │  Validates token    │
                    │  with audience      │
                    │  "demoapp"          │
                    └─────────────────────┘
```

### Token Flow

1. **Client Registration** container uses the **SPIFFE ID** to register the caller workload with Keycloak
2. **Caller** obtains a token from Keycloak using the auto-registered client credentials
3. **AuthProxy + Envoy** (sidecar) intercepts the outgoing request and exchanges the token for one with audience `demoapp`
4. **Demo App** (target server) validates the exchanged token

### Components in Caller Pod

| Container | Type | Purpose |
|-----------|------|---------|
| `proxy-init` | init | Sets up iptables to intercept outgoing traffic (excludes port 8080 for Keycloak) |
| `client-registration` | container | Registers workload with Keycloak using SPIFFE ID, saves credentials to `/shared/` |
| `caller` (netshoot) | container | The application making requests (has curl and jq) |
| `spiffe-helper` | container | Provides SPIFFE credentials (SVID) |
| `auth-proxy` | container | Validates tokens |
| `envoy-proxy` | container | Intercepts traffic and performs token exchange via go-processor |

## Prerequisites

- Kubernetes cluster (Kind recommended for local development)
- SPIRE installed and running (server + agent) - for SPIFFE version
- Keycloak deployed
- Docker/Podman for building images

### Quick Setup with Kagenti

The easiest way to get all prerequisites is to use the [Kagenti Ansible installer](https://github.com/kagenti/kagenti/blob/main/docs/install.md#ansible-based-installer-recommended).

## End-to-End Testing Guide

### Step 1: Build and Load AuthProxy Images

```bash
cd AuthBridge/AuthProxy

# Build all images
make build-images

# Load images into Kind cluster
make load-images
```

### Step 2: Configure Keycloak

Port-forward Keycloak to access it locally:

```bash
kubectl port-forward service/keycloak-service -n keycloak 8080:8080
```

In a new terminal, run the setup script:

```bash
cd AuthBridge/unified-demo

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Run setup script
python setup_keycloak.py
```

The script creates:
- `demo` realm
- `authproxy` client (for token exchange)
- `demoapp` client (token exchange target audience)
- `authproxy-aud` scope (realm default - all clients get it)
- `demoapp-aud` scope (for exchanged tokens)

**Important:** Copy the `authproxy` client secret from the output.

### Step 3: Deploy the Secret

```bash
# Create the auth-proxy-config secret
kubectl apply -f k8s/auth-proxy-config.yaml

# IMPORTANT: Update with the actual authproxy client secret from Step 2
# Copy the secret value from the setup_keycloak.py output
kubectl patch secret auth-proxy-config -p '{"stringData":{"CLIENT_SECRET":"YOUR_AUTHPROXY_SECRET_HERE"}}'

# Verify it was updated (should NOT show REPLACE_WITH_AUTHPROXY_SECRET)
kubectl get secret auth-proxy-config -o jsonpath='{.data.CLIENT_SECRET}' | base64 -d && echo
```

### Step 4: Configure Image Pull Secret (if needed)

If using Kagenti, copy the ghcr secret:

```bash
kubectl get secret ghcr-secret -n team1 -o yaml | sed 's/namespace: team1/namespace: default/' | kubectl apply -f -
```

### Step 5: Deploy the Demo

```bash
# With SPIFFE (requires SPIRE)
kubectl apply -f k8s/unified-deployment.yaml

# OR without SPIFFE
kubectl apply -f k8s/unified-deployment-no-spiffe.yaml
```

Wait for deployments:

```bash
kubectl wait --for=condition=available --timeout=180s deployment/caller
kubectl wait --for=condition=available --timeout=120s deployment/demo-app
```

### Step 6: Test the Flow

```bash
# Exec into the caller container
kubectl exec -it deployment/caller -c caller -- sh
```

Inside the container (or run as a single command):

```bash
# Credentials are auto-populated by client-registration
CLIENT_ID=$(cat /shared/client-id.txt)
CLIENT_SECRET=$(cat /shared/client-secret.txt)

echo "Client ID: $CLIENT_ID"
echo "Client Secret: $CLIENT_SECRET"

# Get a token from Keycloak
TOKEN=$(curl -sX POST http://keycloak-service.keycloak.svc:8080/realms/demo/protocol/openid-connect/token \
  -d 'grant_type=client_credentials' \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET" | jq -r '.access_token')

echo "Token obtained!"

# Verify token audience (should be "authproxy")
echo $TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | jq '{aud, azp, scope}'

# Call demo-app (AuthProxy will exchange token for "demoapp" audience)
curl -H "Authorization: Bearer $TOKEN" http://demo-app-service:8081/test

# Expected output: "authorized"
```

**Or run the complete test as a single command:**

```bash
kubectl exec deployment/caller -c caller -- sh -c '
CLIENT_ID=$(cat /shared/client-id.txt)
CLIENT_SECRET=$(cat /shared/client-secret.txt)
TOKEN=$(curl -s http://keycloak-service.keycloak.svc:8080/realms/demo/protocol/openid-connect/token \
  -d "grant_type=client_credentials" -d "client_id=$CLIENT_ID" -d "client_secret=$CLIENT_SECRET" | jq -r ".access_token")
echo "Token audience: $(echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq -r .aud)"
echo "Result: $(curl -s -H "Authorization: Bearer $TOKEN" http://demo-app-service:8081/test)"
'
```

## Verification

### Check Client Registration

```bash
kubectl logs deployment/caller -c client-registration
```

You should see:

```shell
SPIFFE credentials ready!
Client ID (SPIFFE ID): spiffe://...
Created Keycloak client "spiffe://..."
Client registration complete!
```

### Check Token Exchange

```bash
kubectl logs deployment/caller -c envoy-proxy 2>&1 | grep -i "token"
```

You should see:

```shell
[Token Exchange] All required headers present, attempting token exchange
[Token Exchange] Successfully exchanged token
[Token Exchange] Replacing token in Authorization header
```

### Check Demo App

```bash
kubectl logs deployment/demo-app
```

You should see:

```shell
[JWT Debug] Successfully validated token
[JWT Debug] Audience: [demoapp]
Authorized request: GET /test
```

## Troubleshooting

### Client Registration Can't Reach Keycloak

**Symptom:** `Connection refused` when connecting to Keycloak

**Fix:** Ensure `OUTBOUND_PORTS_EXCLUDE: "8080"` is set in proxy-init env vars. This excludes Keycloak port from iptables redirect.

### Token Exchange Fails with "Audience not found"

**Symptom:** `{"error":"invalid_client","error_description":"Audience not found"}`

**Fix:** The `demoapp` client must exist in Keycloak. Run `setup_keycloak.py` which creates it.

### Token Exchange Fails with "Client not enabled to retrieve service account"

**Symptom:** `{"error":"unauthorized_client","error_description":"Client not enabled to retrieve service account"}`

**Fix:** The caller's client needs `serviceAccountsEnabled: true`. This is set in the updated `client_registration.py`.

### curl/jq Not Found in Caller Container

**Symptom:** `sh: curl: not found` or `sh: jq: not found`

**Fix:** The caller container should use `nicolaka/netshoot:latest` image which has these tools pre-installed.

### No Token Received

**Symptom:** `echo $TOKEN=null`

**Fix:** Make sure the `serviceAccountsEnabled` is present in the `client-registration` image.

#### Enable Service Accounts for the Registered Client

The published `client-registration` image doesn't yet have the `serviceAccountsEnabled` fix. Run this to enable it:

```bash
kubectl exec deployment/caller -c caller -- sh -c '
CLIENT_ID=$(cat /shared/client-id.txt)
echo "Enabling service accounts for: $CLIENT_ID"

ADMIN_TOKEN=$(curl -s http://keycloak-service.keycloak.svc:8080/realms/master/protocol/openid-connect/token \
  -d "grant_type=password" -d "client_id=admin-cli" -d "username=admin" -d "password=admin" | jq -r ".access_token")

INTERNAL_ID=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://keycloak-service.keycloak.svc:8080/admin/realms/demo/clients?clientId=$CLIENT_ID" | jq -r ".[0].id")

curl -s -X PUT -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  "http://keycloak-service.keycloak.svc:8080/admin/realms/demo/clients/$INTERNAL_ID" \
  -d "{\"clientId\": \"$CLIENT_ID\", \"serviceAccountsEnabled\": true}"

echo "Done!"
'
```

### View All Logs

```bash
# Caller pod containers
kubectl logs deployment/caller -c caller
kubectl logs deployment/caller -c client-registration
kubectl logs deployment/caller -c spiffe-helper
kubectl logs deployment/caller -c auth-proxy
kubectl logs deployment/caller -c envoy-proxy

# Demo app
kubectl logs deployment/demo-app
```

## Cleanup

```bash
kubectl delete -f k8s/unified-deployment.yaml
# OR
kubectl delete -f k8s/unified-deployment-no-spiffe.yaml

kubectl delete -f k8s/auth-proxy-config.yaml
```

## References

- [AuthBridge Client Registration](../client-registration/README.md)
- [AuthProxy](../AuthProxy/README.md)
- [Kagenti Installation](https://github.com/kagenti/kagenti/blob/main/docs/install.md)
- [SPIRE Documentation](https://spiffe.io/docs/latest/)
