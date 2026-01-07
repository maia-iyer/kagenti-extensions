# AuthBridge

AuthBridge provides **secure, transparent token management** for Kubernetes workloads. It combines automatic [client registration](./client-registration/) with [token exchange](./AuthProxy/) capabilities, enabling zero-trust authentication flows with [SPIFFE/SPIRE](https://spiffe.io) integration.

> **📘 Looking to run the demo?** See the [Demo Guide](./demo.md) for step-by-step instructions.

## What AuthBridge Does

AuthBridge solves the challenge of **secure service-to-service authentication** in Kubernetes:

1. **Automatic Identity** - Workloads automatically obtain their identity from SPIFFE/SPIRE and register as Keycloak clients using their SPIFFE ID (e.g., `spiffe://localtest.me/ns/authbridge/sa/agent`)

2. **Token-Based Authorization** - Callers obtain JWT tokens from Keycloak with the target's identity as the audience, authorizing them to invoke specific services

3. **Transparent Token Exchange** - A sidecar intercepts outgoing requests, validates incoming tokens, and exchanges them for tokens with the appropriate target audience—all without application code changes

4. **Target Service Validation** - Target services validate the exchanged token, ensuring it has the correct audience before authorizing requests

## End-to-End Flow

**Initialization (Agent Pod Startup):**
```
  SPIRE Agent              Agent Pod                         Keycloak
       │                        │                                │
       │  0. SVID               │                                │
       │───────────────────────►│  SPIFFE Helper                 │
       │  (SPIFFE ID)           │                                │
       │                        │                                │
       │                        │  1. Register client            │
       │                        │  (client_id = SPIFFE ID)       │
       │                        │───────────────────────────────►│
       │                        │  Client Registration           │
       │                        │                                │
       │                        │◄───────────────────────────────│
       │                        │  client_secret                 │
       │                        │  (saved to /shared/)           │
```

**Runtime Flow:**
```
  Caller              Agent Pod                Auth Target      Keycloak
    │                     │                        │               │
    │  2. Get token       │                        │               │
    │  (aud: Agent's SPIFFE ID)                    │               │
    │─────────────────────────────────────────────────────────────►│
    │◄─────────────────────────────────────────────────────────────│
    │  Token (self-aud)   │                        │               │
    │                     │                        │               │
    │  3. Pass token      │                        │               │
    │  to Agent           │                        │               │
    │────────────────────►│                        │               │
    │                     │                        │               │
    │                     │  4. Agent calls        │               │
    │                     │  Auth Target with      │               │
    │                     │  Caller's token        │               │
    │                     │──────────┐             │               │
    │                     │          │             │               │
    │                     │  AuthProxy intercepts  │               │
    │                     │  validates aud=Agent   │               │
    │                     │          │             │               │
    │                     │  5. Token Exchange     │               │
    │                     │  (using Agent's creds) │               │
    │                     │───────────────────────────────────────►│
    │                     │◄───────────────────────────────────────│
    │                     │  New token (aud: auth-target)          │
    │                     │          │             │               │
    │                     │  6. Forward request    │               │
    │                     │  with exchanged token  │               │
    │                     │───────────────────────►│               │
    │                     │                        │               │
    │                     │◄───────────────────────│               │
    │                     │  "authorized"          │               │
    │◄────────────────────│                        │               │
    │  Response           │                        │               │
```

<details>
<summary><b>📊 Mermaid Diagram (click to expand)</b></summary>

```mermaid
sequenceDiagram
    autonumber
    participant SPIRE as SPIRE Agent
    participant Helper as SPIFFE Helper
    participant Reg as Client Registration
    participant Caller as Caller
    participant Agent as Agent
    participant Envoy as AuthProxy (Envoy + Ext Proc)
    participant KC as Keycloak
    participant Target as Auth Target

    Note over Helper,SPIRE: Agent Pod Initialization
    SPIRE->>Helper: SVID (SPIFFE credentials)
    Helper->>Reg: JWT with SPIFFE ID
    Reg->>KC: Register client (client_id = SPIFFE ID)
    KC-->>Reg: Client credentials (saved to /shared/)

    Note over Caller,Target: Runtime Flow
    Caller->>KC: Get token (aud: Agent's SPIFFE ID)
    KC-->>Caller: Token with self-aud scope
    
    Caller->>Agent: Pass token
    Agent->>Envoy: Call Auth Target with Caller's token
    
    Note over Envoy: AuthProxy intercepts<br/>Validates aud = Agent's ID<br/>Uses Agent's credentials
    
    Envoy->>KC: Token Exchange (Agent's creds)
    KC-->>Envoy: New Token (aud: auth-target)
    
    Envoy->>Target: Request + Exchanged Token
    Target->>Target: Validate token (aud: auth-target)
    Target-->>Agent: "authorized"
    Agent-->>Caller: Response
```

</details>

## What Gets Verified

| Step | Component | Verification |
|------|-----------|--------------|
| 0 | SPIFFE Helper | SVID obtained from SPIRE Agent |
| 1 | Client Registration | Agent registered with Keycloak (client_id = SPIFFE ID) |
| 2 | Caller | Token obtained with `aud: Agent's SPIFFE ID` (via `agent-spiffe-aud` scope) |
| 3 | Agent | Token received from Caller |
| 4 | AuthProxy | Token validated (aud matches Agent's identity) |
| 5 | Ext Proc | Token exchanged using Agent's credentials → `aud: auth-target` |
| 6 | Auth Target | Token validated, returns `"authorized"` |

## Key Security Properties

- **No Static Secrets** - Credentials are dynamically generated during registration
- **Short-Lived Tokens** - JWT tokens expire and must be refreshed
- **Self-Audience Scoping** - Tokens include the Agent's own identity as audience, enabling token exchange
- **Same Identity for Exchange** - AuthProxy uses the Agent's credentials (same SPIFFE ID), matching the token's audience
- **Transparent to Application** - Token exchange is handled by the sidecar; applications don't need to implement it

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                           AGENT POD                                    │
│                       (namespace: authbridge)                          │
│                      (serviceAccount: agent)                           │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Init Container: proxy-init (iptables setup)                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Containers                                 │   │
│  │  ┌──────────────┐  ┌─────────────────┐  ┌────────────────────┐  │   │
│  │  │    Agent     │  │  SPIFFE Helper  │  │    AuthProxy +     │  │   │
│  │  │  (netshoot)  │  │  (provides      │  │    Envoy + Go Proc │  │   │
│  │  │              │  │   SPIFFE creds) │  │  (token exchange)  │  │   │
│  │  └──────┬───────┘  └─────────────────┘  └──────────┬─────────┘  │   │
│  │                                                                 │   │
│  │  ┌───────────────────────────────────────────────────────────┐  │   │
│  │  │ client-registration (registers Agent with Keycloak)       │  │   │
│  │  └───────────────────────────────────────────────────────────┘  │   │
│  └─────────┼───────────────────────────────────────────┼───────────┘   │
│            │ Caller's token (aud: SPIFFE ID)           │               │
│            └───────────────────────────────────────────┘               │
│                              │                                         │
└──────────────────────────────┼─────────────────────────────────────────┘
                               │ Token exchanged for auth-target audience
                               │ (using Agent's own credentials)
                               ▼
                    ┌─────────────────────┐
                    │   AUTH TARGET POD   │
                    │   (Target Server)   │
                    │                     │
                    │  Validates token    │
                    │  with audience      │
                    │  "auth-target"      │
                    └─────────────────────┘
```

<details>
<summary><b>📊 Mermaid Architecture Diagram (click to expand)</b></summary>

```mermaid
flowchart TB
    subgraph AgentPod["AGENT POD (namespace: authbridge, sa: agent)"]
        subgraph Init["Init Container"]
            ProxyInit["proxy-init<br/>(iptables setup)"]
        end
        subgraph Containers["Containers"]
            Agent["agent<br/>(netshoot)"]
            SpiffeHelper["SPIFFE Helper<br/>(provides SVID)"]
            ClientReg["client-registration<br/>(registers with Keycloak)"]
            subgraph Sidecar["AuthProxy Sidecar"]
                AuthProxy["auth-proxy"]
                Envoy["envoy-proxy"]
                ExtProc["ext-proc"]
            end
        end
    end

    subgraph TargetPod["AUTH TARGET POD"]
        AuthTarget["auth-target<br/>(validates tokens)"]
    end

    subgraph External["External Services"]
        SPIRE["SPIRE Agent"]
        Keycloak["Keycloak"]
    end

    Caller["Caller<br/>(external)"]

    SPIRE --> SpiffeHelper
    SpiffeHelper --> ClientReg
    ClientReg --> Keycloak
    Caller -->|"1. Get token"| Keycloak
    Caller -->|"2. Pass token"| Agent
    Agent -->|"3. Request + Token"| Envoy
    Envoy --> ExtProc
    ExtProc -->|"4. Token Exchange"| Keycloak
    Envoy -->|"5. Request + Exchanged Token"| AuthTarget
    AuthTarget -->|"6. Response"| Agent
    Agent -->|"7. Response"| Caller

    style AgentPod fill:#e1f5fe
    style TargetPod fill:#e8f5e9
    style Sidecar fill:#fff3e0
    style External fill:#fce4ec
    style Caller fill:#fff9c4
```

</details>

## Components

### Agent Pod

| Container | Type | Purpose |
|-----------|------|---------|
| `proxy-init` | init | Sets up iptables to intercept outgoing traffic (excludes port 8080 for Keycloak) |
| `client-registration` | container | Registers workload with Keycloak using SPIFFE ID, saves credentials to `/shared/` |
| `agent` (netshoot) | container | The agent application receiving tokens from Callers |
| `spiffe-helper` | container | Provides SPIFFE credentials (SVID) |
| `auth-proxy` | container | Validates tokens |
| `envoy-proxy` | container | Intercepts traffic and performs token exchange via Ext Proc |

### Auth Target Pod

A target service that validates incoming tokens have `aud: auth-target`.

## Prerequisites

- Kubernetes cluster (Kind recommended for local development)
- SPIRE installed and running (server + agent) - for SPIFFE version
- Keycloak deployed
- Docker/Podman for building images

### Quick Setup

The easiest way to get all prerequisites is to use the [Kagenti Ansible installer](https://github.com/kagenti/kagenti/blob/main/docs/install.md#ansible-based-installer-recommended).

## Getting Started

See the **[Demo Guide](./demo.md)** for complete step-by-step instructions on:

- Building and loading images
- Configuring Keycloak
- Deploying the demo
- Testing the token exchange flow
- Inspecting token claims
- Troubleshooting common issues

## Component Documentation

- [AuthProxy](AuthProxy/README.md) - Token validation and exchange proxy
- [Client Registration](client-registration/README.md) - Automatic Keycloak client registration with SPIFFE

## References

- [Kagenti Installation](https://github.com/kagenti/kagenti/blob/main/docs/install.md)
- [SPIRE Documentation](https://spiffe.io/docs/latest/)
- [OAuth 2.0 Token Exchange (RFC 8693)](https://www.rfc-editor.org/rfc/rfc8693)
