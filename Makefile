.PHONY: all cluster-local deploy-local infra-up infra-down deploy-prod \
        port-forward-grafana port-forward-argocd port-forward-jaeger \
        port-forward-dashboard port-forward-all chaos-on chaos-off \
        logs-ai logs-operator build-images push-images clean help

CLUSTER_NAME   ?= infragpt
AWS_REGION     ?= us-east-1
DOCKER_REGISTRY ?= your-dockerhub-username
IMAGE_TAG      ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "latest")

# ─── Local Development ────────────────────────────────────────────────────────

cluster-local: ## Create local k3d cluster
	k3d cluster create $(CLUSTER_NAME) \
		--agents 2 \
		--port "8080:80@loadbalancer" \
		--port "8443:443@loadbalancer" \
		--k3s-arg "--disable=traefik@server:0"
	kubectl cluster-info

cluster-local-delete: ## Delete local k3d cluster
	k3d cluster delete $(CLUSTER_NAME)

deploy-local: ## Deploy full stack to local k3d cluster
	$(MAKE) install-argocd
	$(MAKE) install-monitoring
	$(MAKE) install-logging
	$(MAKE) install-vault
	$(MAKE) install-kyverno
	$(MAKE) install-operator
	$(MAKE) install-ai-engine
	$(MAKE) install-sample-app
	@echo "✅ Full stack deployed locally"

# ─── Infrastructure ───────────────────────────────────────────────────────────

infra-up: ## Provision AWS infrastructure with Terraform
	cd terraform/vpc && terraform init && terraform apply -auto-approve
	cd terraform/rds && terraform init && terraform apply -auto-approve
	cd terraform/eks-cluster && terraform init && terraform apply -auto-approve
	aws eks update-kubeconfig --name $(CLUSTER_NAME) --region $(AWS_REGION)
	@echo "✅ AWS infrastructure provisioned"

infra-down: ## Destroy AWS infrastructure
	@echo "⚠️  This will destroy ALL AWS resources. Press Ctrl+C to cancel."
	@sleep 5
	cd terraform/eks-cluster && terraform destroy -auto-approve
	cd terraform/rds && terraform destroy -auto-approve
	cd terraform/vpc && terraform destroy -auto-approve

infra-plan: ## Show Terraform plan without applying
	cd terraform/vpc && terraform init -backend=false && terraform plan
	cd terraform/eks-cluster && terraform init -backend=false && terraform plan

# ─── Component Installation ───────────────────────────────────────────────────

install-argocd: ## Install ArgoCD
	kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
	kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd
	kubectl apply -f argocd/projects/
	kubectl apply -f argocd/applications/

install-monitoring: ## Install kube-prometheus-stack
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update
	kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
		--namespace monitoring \
		--values k8s/base/monitoring/values.yaml \
		--wait --timeout 10m

install-logging: ## Install Loki + Promtail
	helm repo add grafana https://grafana.github.io/helm-charts
	helm repo update
	kubectl create namespace logging --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install loki grafana/loki-stack \
		--namespace logging \
		--values k8s/base/logging/loki-values.yaml \
		--wait

install-vault: ## Install HashiCorp Vault
	helm repo add hashicorp https://helm.releases.hashicorp.com
	helm repo update
	kubectl create namespace vault --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install vault hashicorp/vault \
		--namespace vault \
		--values vault/helm-values.yaml \
		--wait

install-kyverno: ## Install Kyverno policy engine
	helm repo add kyverno https://kyverno.github.io/kyverno/
	helm repo update
	kubectl create namespace kyverno --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install kyverno kyverno/kyverno \
		--namespace kyverno \
		--wait
	kubectl apply -f k8s/base/policies/

install-operator: ## Install self-healing operator
	kubectl create namespace infragpt-system --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -f k8s/base/crds/
	kubectl apply -f k8s/base/operator/
	kubectl apply -f k8s/base/healing-policies/

install-ai-engine: ## Install AI anomaly detection engine
	kubectl create namespace ai-engine --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -k k8s/overlays/local/ai-engine/

install-sample-app: ## Install sample microservices application
	kubectl create namespace production --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -k k8s/overlays/local/sample-app/

# ─── Production Deployment ────────────────────────────────────────────────────

deploy-prod: ## Deploy to production EKS via ArgoCD
	kubectl apply -f argocd/applicationset.yaml
	argocd app sync --grpc-web infragpt-production
	@echo "✅ Production deployment triggered"

# ─── Port Forwarding ──────────────────────────────────────────────────────────

port-forward-grafana: ## Access Grafana at http://localhost:3000 (admin/admin)
	@echo "Grafana: http://localhost:3000 (admin/prom-operator)"
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80

port-forward-argocd: ## Access ArgoCD at http://localhost:8080
	@echo "ArgoCD: http://localhost:8080"
	@echo "Password: $$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
	kubectl port-forward -n argocd svc/argocd-server 8080:443

port-forward-jaeger: ## Access Jaeger at http://localhost:16686
	@echo "Jaeger: http://localhost:16686"
	kubectl port-forward -n monitoring svc/jaeger-query 16686:16686

port-forward-prometheus: ## Access Prometheus at http://localhost:9090
	@echo "Prometheus: http://localhost:9090"
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090

port-forward-dashboard: ## Access React dashboard at http://localhost:5173
	@echo "Dashboard: http://localhost:5173"
	cd dashboard && npm run dev

port-forward-all: ## Open all dashboards (runs in background)
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &
	kubectl port-forward -n argocd svc/argocd-server 8080:443 &
	kubectl port-forward -n monitoring svc/jaeger-query 16686:16686 &
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
	@echo "All dashboards running in background. Use 'make kill-port-forwards' to stop."

kill-port-forwards: ## Kill all background port-forwards
	pkill -f "kubectl port-forward" || true

# ─── Docker Images ────────────────────────────────────────────────────────────

build-images: ## Build all Docker images
	docker build -t $(DOCKER_REGISTRY)/infragpt-frontend:$(IMAGE_TAG) apps/frontend/
	docker build -t $(DOCKER_REGISTRY)/infragpt-backend:$(IMAGE_TAG) apps/backend/
	docker build -t $(DOCKER_REGISTRY)/infragpt-ai-engine:$(IMAGE_TAG) ai-engine/
	docker build -t $(DOCKER_REGISTRY)/infragpt-operator:$(IMAGE_TAG) self-healing-operator/

push-images: build-images ## Build and push all Docker images
	docker push $(DOCKER_REGISTRY)/infragpt-frontend:$(IMAGE_TAG)
	docker push $(DOCKER_REGISTRY)/infragpt-backend:$(IMAGE_TAG)
	docker push $(DOCKER_REGISTRY)/infragpt-ai-engine:$(IMAGE_TAG)
	docker push $(DOCKER_REGISTRY)/infragpt-operator:$(IMAGE_TAG)

# ─── Chaos Engineering ────────────────────────────────────────────────────────

chaos-on: ## Enable chaos mode (random pod deletion every 60s)
	kubectl patch configmap chaos-config -n production \
		--patch '{"data":{"enabled":"true"}}' 2>/dev/null || \
	kubectl create configmap chaos-config -n production --from-literal=enabled=true
	@echo "🔥 Chaos mode ENABLED — pods will be randomly deleted every 60s"

chaos-off: ## Disable chaos mode
	kubectl patch configmap chaos-config -n production \
		--patch '{"data":{"enabled":"false"}}'
	@echo "✅ Chaos mode DISABLED"

# ─── Logs ─────────────────────────────────────────────────────────────────────

logs-ai: ## Tail AI engine logs
	kubectl logs -n ai-engine -l app=ai-engine -f --tail=100

logs-operator: ## Tail self-healing operator logs
	kubectl logs -n infragpt-system -l app=self-healing-operator -f --tail=100

logs-frontend: ## Tail frontend logs
	kubectl logs -n production -l app=frontend -f --tail=100

logs-backend: ## Tail backend logs
	kubectl logs -n production -l app=backend -f --tail=100

# ─── Utilities ────────────────────────────────────────────────────────────────

get-argocd-password: ## Get ArgoCD initial admin password
	@kubectl -n argocd get secret argocd-initial-admin-secret \
		-o jsonpath='{.data.password}' | base64 -d && echo

vault-init: ## Initialize and unseal Vault (dev mode)
	kubectl exec -n vault vault-0 -- vault operator init -key-shares=1 -key-threshold=1 \
		-format=json > vault/vault-keys.json
	@echo "⚠️  vault-keys.json contains unseal key and root token — DO NOT COMMIT"
	kubectl exec -n vault vault-0 -- vault operator unseal \
		$$(cat vault/vault-keys.json | jq -r '.unseal_keys_b64[0]')

vault-setup: vault-init ## Configure Vault auth and secrets
	bash vault/setup.sh

clean: ## Remove generated files
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name ".terraform" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.tfstate*" -delete 2>/dev/null || true

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
