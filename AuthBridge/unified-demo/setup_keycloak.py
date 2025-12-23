"""
setup_keycloak.py - Unified AuthBridge Demo Setup

This script configures Keycloak for the unified AuthBridge demo that combines:
1. Client Registration with SPIFFE ID (for the caller)
2. AuthProxy sidecar for token exchange
3. Demo App (target server) that validates exchanged tokens

Architecture:
  Caller Pod (BusyBox + SPIFFE Helper + Client Registration + AuthProxy)
       |
       | Token with audience "authproxy" (or caller's SPIFFE ID)
       v
  AuthProxy (Envoy) exchanges token
       |
       | Token with audience "demoapp"
       v
  Demo App (validates token)

Clients created:
- authproxy: Used by AuthProxy to exchange tokens for demo-app access

Client Scopes created:
- authproxy-aud: Adds "authproxy" to token audience
- demoapp-aud: Adds "demoapp" to token audience

Note: The caller client is auto-registered by the client-registration init container
using the SPIFFE ID as the client ID.
"""

from keycloak import KeycloakAdmin, KeycloakPostError
import sys

KEYCLOAK_URL = "http://keycloak.localtest.me:8080"
KEYCLOAK_REALM = "demo"
KEYCLOAK_ADMIN_USERNAME = "admin"
KEYCLOAK_ADMIN_PASSWORD = "admin"


def get_or_create_realm(keycloak_admin, realm_name):
    """Create realm if it doesn't exist."""
    try:
        realms = keycloak_admin.get_realms()
        for realm in realms:
            if realm['realm'] == realm_name:
                print(f"Realm '{realm_name}' already exists.")
                return
        keycloak_admin.create_realm({
            "realm": realm_name,
            "enabled": True,
            "displayName": realm_name,
        })
        print(f"Created realm '{realm_name}'.")
    except Exception as e:
        print(f"Error checking/creating realm: {e}")


def get_or_create_client(keycloak_admin, client_payload):
    """Create client if doesn't exist, return internal client ID."""
    client_id = client_payload['clientId']
    existing_client_id = keycloak_admin.get_client_id(client_id)
    if existing_client_id:
        print(f"Client '{client_id}' already exists.")
        return existing_client_id
    internal_id = keycloak_admin.create_client(client_payload)
    print(f"Created client '{client_id}'.")
    return internal_id


def get_or_create_client_scope(keycloak_admin, scope_payload):
    """Create client scope if doesn't exist, return scope ID."""
    scope_name = scope_payload.get("name")
    scopes = keycloak_admin.get_client_scopes()
    for scope in scopes:
        if scope['name'] == scope_name:
            print(f"Client scope '{scope_name}' already exists with ID: {scope['id']}")
            return scope['id']

    try:
        scope_id = keycloak_admin.create_client_scope(scope_payload)
        print(f"Created client scope '{scope_name}': {scope_id}")
        return scope_id
    except KeycloakPostError as e:
        print(f"Could not create client scope '{scope_name}': {e}")
        raise


def add_audience_mapper(keycloak_admin, scope_id, mapper_name, audience):
    """Add audience protocol mapper to a client scope."""
    mapper_payload = {
        "name": mapper_name,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.custom.audience": audience,
            "id.token.claim": "false",
            "access.token.claim": "true",
            "userinfo.token.claim": "false"
        }
    }
    
    try:
        keycloak_admin.add_mapper_to_client_scope(scope_id, mapper_payload)
        print(f"Added audience mapper '{mapper_name}' for audience '{audience}'")
    except Exception as e:
        # Mapper might already exist
        print(f"Note: Could not add mapper '{mapper_name}' (might already exist): {e}")


def main():
    print("=" * 60)
    print("Unified AuthBridge Demo - Keycloak Setup")
    print("=" * 60)
    
    # Connect to Keycloak master realm first
    print(f"\nConnecting to Keycloak at {KEYCLOAK_URL}...")
    try:
        master_admin = KeycloakAdmin(
            server_url=KEYCLOAK_URL,
            username=KEYCLOAK_ADMIN_USERNAME,
            password=KEYCLOAK_ADMIN_PASSWORD,
            realm_name="master",
            user_realm_name="master"
        )
    except Exception as e:
        print(f"Failed to connect to Keycloak: {e}")
        print("\nMake sure Keycloak is running and accessible at:")
        print(f"  {KEYCLOAK_URL}")
        print("\nIf using port-forward, run:")
        print("  kubectl port-forward service/keycloak -n keycloak 8080:8080")
        sys.exit(1)
    
    # Create demo realm if needed
    print(f"\n--- Setting up realm: {KEYCLOAK_REALM} ---")
    get_or_create_realm(master_admin, KEYCLOAK_REALM)
    
    # Switch to demo realm
    keycloak_admin = KeycloakAdmin(
        server_url=KEYCLOAK_URL,
        username=KEYCLOAK_ADMIN_USERNAME,
        password=KEYCLOAK_ADMIN_PASSWORD,
        realm_name=KEYCLOAK_REALM,
        user_realm_name="master"
    )
    
    # Create authproxy client (used by AuthProxy sidecar for token exchange)
    print("\n--- Creating authproxy client ---")
    print("This client is used by the AuthProxy sidecar to exchange tokens")
    authproxy_id = get_or_create_client(keycloak_admin, {
        "clientId": "authproxy",
        "name": "Auth Proxy",
        "enabled": True,
        "publicClient": False,
        "standardFlowEnabled": False,
        "serviceAccountsEnabled": True,
        "attributes": {
            "standard.token.exchange.enabled": "true"
        }
    })
    
    # Create client scopes
    print("\n--- Creating client scopes ---")
    
    # authproxy-aud scope - added to caller's tokens
    # This makes the caller's token valid for AuthProxy
    authproxy_scope_id = get_or_create_client_scope(keycloak_admin, {
        "name": "authproxy-aud",
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true"
        }
    })
    add_audience_mapper(keycloak_admin, authproxy_scope_id, "authproxy-aud", "authproxy")
    
    # demoapp-aud scope - added to exchanged tokens
    # This makes the AuthProxy's exchanged token valid for demo-app
    demoapp_scope_id = get_or_create_client_scope(keycloak_admin, {
        "name": "demoapp-aud",
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "true"
        }
    })
    add_audience_mapper(keycloak_admin, demoapp_scope_id, "demoapp-aud", "demoapp")
    
    # Assign scopes
    print("\n--- Assigning scopes ---")
    
    # Add authproxy-aud as a realm default scope
    # This ensures all clients (including auto-registered ones) get this scope
    # So their tokens will have "authproxy" in the audience
    try:
        keycloak_admin.add_default_default_client_scope(authproxy_scope_id)
        print("Added 'authproxy-aud' as realm default scope (all clients will get it).")
    except Exception as e:
        print(f"Note: Could not add 'authproxy-aud' as default scope (might already exist): {e}")
    
    # authproxy gets demoapp-aud (so its exchanged tokens target demoapp)
    try:
        keycloak_admin.add_client_default_client_scope(authproxy_id, demoapp_scope_id, {})
        print("Assigned 'demoapp-aud' as default scope to 'authproxy'.")
    except Exception as e:
        print(f"Note: Could not assign 'demoapp-aud' scope (might already exist): {e}")
    
    # Retrieve and display secrets
    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    
    try:
        authproxy_secret = keycloak_admin.get_client_secrets(authproxy_id)['value']
        
        print("\n--- authproxy client credentials ---")
        print(f"Client ID: authproxy")
        print(f"Client Secret: {authproxy_secret}")
        
        print("\n" + "=" * 60)
        print("NEXT STEPS")
        print("=" * 60)
        
        print("\n1. Update the auth-proxy-config secret with the authproxy client secret:")
        print(f"\n   kubectl patch secret auth-proxy-config -p '{{\"stringData\":{{\"CLIENT_SECRET\":\"{authproxy_secret}\"}}}}'\n")
        
        print("2. Deploy the unified demo:")
        print("\n   # With SPIFFE (requires SPIRE)")
        print("   kubectl apply -f k8s/unified-deployment.yaml")
        print("\n   # OR without SPIFFE")
        print("   kubectl apply -f k8s/unified-deployment-no-spiffe.yaml\n")
        
        print("3. Wait for pods to be ready:")
        print("\n   kubectl wait --for=condition=available --timeout=120s deployment/caller")
        print("   kubectl wait --for=condition=available --timeout=120s deployment/demo-app\n")
        
        print("4. Test from inside the caller pod:")
        print("""
   kubectl exec -it deployment/caller -c caller -- sh
   
   # Inside the container:
   CLIENT_SECRET=$(cat /shared/client-secret.txt)
   
   # For no-spiffe version, client_id is 'caller'
   # For spiffe version, check Keycloak for the registered SPIFFE ID
   TOKEN=$(curl -sX POST \\
     http://keycloak-service.keycloak.svc:8080/realms/demo/protocol/openid-connect/token \\
     -d 'grant_type=client_credentials' \\
     -d 'client_id=caller' \\
     -d "client_secret=$CLIENT_SECRET" | jq -r '.access_token')
   
   # Call demo-app (AuthProxy will exchange the token)
   curl -H "Authorization: Bearer $TOKEN" http://demo-app-service:8081/test
   # Expected: "authorized"
""")
        
        print("\nNote: The caller client is auto-registered by the client-registration")
        print("init container. For SPIFFE version, it uses the SPIFFE ID as client ID.")
        
    except Exception as e:
        print(f"Could not retrieve secrets: {e}")


if __name__ == "__main__":
    main()
