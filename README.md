# InfraGPT — AI-Powered Self-Healing Kubernetes Platform

[![CI](https://github.com/your-org/infragpt/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/infragpt/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

InfraGPT is a production-grade, AI-powered Kubernetes platform that watches your infrastructure 24/7, detects anomalies before they become incidents, heals itself automatically, and explains everything in plain English on Slack.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         InfraGPT Platform                           │
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│  │ Frontend │    │ Backend  │    │  Redis   │    │  PostgreSQL  │  │
│  │ Node.js  │───▶│ FastAPI  │───▶│  Cache   │    │  Incidents   │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────────┘  │
│        │                │                                           │
│        ▼                ▼                                           │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Observability Stack                        │   │
│  │  Prometheus ──▶ Grafana ──▶ Loki ──▶ Jaeger (Traces)       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│        │                                                            │
│        ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    AI Engine                                 │   │
│  │  data_collector ──▶ train ──▶ predict ──▶ root_cause_analyzer│  │
│  │  (Prophet + Isolation Forest + LLM)                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│        │                                                            │
│        ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Self-Healing Operator (kopf)                    │   │
│  │  HealingPolicy CRD ──▶ Rollback / Restart / Scale / Notify  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│  │  ArgoCD  │    │  Vault   │    │ Kyverno  │    │  React UI    │  │
│  │  GitOps  │    │ Secrets  │    │ Policies │    │  Dashboard   │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │   AWS EKS + VPC    │
                    │   (Terraform IaC)  │
                    └────────────────────┘
```

## Features

- **AI Anomaly Detection** — Facebook Prophet + Isolation Forest models trained on 30 days of Prometheus metrics
- **LLM Root Cause Analysis** — GPT-4/Claude explains incidents in plain English with deployment correlation
- **Self-Healing Operator** — Custom Kubernetes Operator auto-rolls back, restarts, or scales based on HealingPolicy CRDs
- **Full GitOps** — ArgoCD watches this repo; every Git push is a deployment
- **Complete Observability** — Metrics (Prometheus/Grafana), Logs (Loki/Promtail), Traces (Jaeger/OpenTelemetry)
- **Policy Enforcement** — Kyverno blocks non-compliant workloads at admission time
- **Secret Management** — HashiCorp Vault with Kubernetes auth; zero secrets in Git
- **Cost Optimizer** — Detects over-provisioned pods and estimates monthly savings
- **Chaos Mode** — Intentionally breaks things to prove self-healing works

## Quick Start

### Prerequisites

```bash
# Install required tools
brew install kubectl helm terraform k9s
brew install argocd
brew tap weaveworks/tap && brew install weaveworks/tap/eksctl
pip install awscli
aws configure
```

### Local Development (k3d)

```bash
# Create local cluster
make cluster-local

# Deploy full stack locally
make deploy-local

# Open dashboards
make port-forward-all
```

### Production (AWS EKS)

```bash
# Provision infrastructure
make infra-up

# Deploy applications
make deploy-prod

# Destroy everything
make infra-down
```

## Directory Structure

```
infragpt/
├── terraform/              # Infrastructure as Code
│   ├── vpc/                # VPC, subnets, NAT gateway
│   ├── eks-cluster/        # EKS cluster + node groups
│   └── rds/                # PostgreSQL RDS instance
├── k8s/                    # Kubernetes manifests (Kustomize)
│   ├── base/               # Base configurations
│   │   ├── sample-app/     # Frontend + Backend + Redis
│   │   ├── monitoring/     # Prometheus + Grafana + Loki
│   │   ├── logging/        # Promtail DaemonSet
│   │   ├── argocd/         # ArgoCD install
│   │   ├── crds/           # Custom Resource Definitions
│   │   ├── operator/       # Self-healing operator
│   │   ├── policies/       # Kyverno policies
│   │   └── healing-policies/ # HealingPolicy instances
│   └── overlays/
│       ├── local/          # k3d overrides
│       ├── staging/        # Staging overrides
│       └── production/     # Production overrides
├── argocd/                 # ArgoCD Applications + Projects
├── ai-engine/              # Anomaly detection + root cause analysis
├── self-healing-operator/  # Kubernetes Operator (kopf)
├── dashboard/              # React frontend
├── vault/                  # Vault policies + config
├── .github/workflows/      # CI/CD pipelines
└── Makefile                # Convenience commands
```

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make cluster-local` | Create k3d cluster |
| `make deploy-local` | Deploy all components locally |
| `make infra-up` | Provision AWS infrastructure |
| `make infra-down` | Destroy AWS infrastructure |
| `make deploy-prod` | Deploy to production EKS |
| `make port-forward-grafana` | Access Grafana at localhost:3000 |
| `make port-forward-argocd` | Access ArgoCD at localhost:8080 |
| `make port-forward-dashboard` | Access React dashboard at localhost:5173 |
| `make chaos-on` | Enable chaos mode |
| `make chaos-off` | Disable chaos mode |
| `make logs-ai` | Tail AI engine logs |
| `make logs-operator` | Tail operator logs |

## Interview Talking Points

1. **Why GitOps?** — Git is the single source of truth. Every change is auditable, reversible, and peer-reviewed via PRs.
2. **Why Prophet for anomaly detection?** — Cluster metrics have strong daily/weekly seasonality. Prophet handles this natively without feature engineering.
3. **Why a Kubernetes Operator vs a script?** — Operators are level-triggered (continuously reconcile desired vs actual state), not edge-triggered. They survive restarts and handle partial failures gracefully.
4. **Why Kyverno over OPA/Gatekeeper?** — Kyverno uses Kubernetes-native YAML policies, no Rego language to learn. Easier to audit and maintain.
5. **MTTR improvement** — Self-healing reduces mean time to recovery from ~15 minutes (human response) to ~90 seconds (automated detection + action).
