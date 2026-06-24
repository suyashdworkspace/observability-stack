# 🔭 Dockerized Application Observability Stack

> **Full-stack observability platform** implementing the three pillars of observability — Metrics, Logs, and Traces — for containerized applications using production-grade open-source tools.

[![CI Status](https://github.com/suyashdworkspace/observability-stack/actions/workflows/observability-ci.yml/badge.svg)](https://github.com/suyashdworkspace/observability-stack/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)](https://docs.docker.com/compose/)
[![Prometheus](https://img.shields.io/badge/Prometheus-v2.51-E6522C?logo=prometheus)](https://prometheus.io/)
[![Grafana](https://img.shields.io/badge/Grafana-v10.4-F46800?logo=grafana)](https://grafana.com/)

---

## 🏗️ Architecture

```
┌─────────────┐    metrics    ┌─────────────┐    query    ┌─────────────┐
│  FastAPI    │◄──────────────│ Prometheus  │────────────►│   Grafana   │
│  + OTEL SDK │               │ + Rules     │             │  Dashboards │
└──────┬──────┘               └──────┬──────┘             └──────┬──────┘
       │ OTLP/gRPC                   │ alerts                    │ LogQL
       ▼                             ▼                            ▼
┌─────────────┐             ┌─────────────┐             ┌─────────────┐
│    OTEL     │──► Jaeger   │ Alertmanager│──► SNS      │    Loki     │
│  Collector  │             │             │    (Boto3)  │             │
└─────────────┘             └─────────────┘             └──────▲──────┘
                                                                │ push
                                                         ┌─────────────┐
                                                         │  Promtail   │
                                                         └─────────────┘
```

**Observability Pillars:**
| Pillar | Collection | Storage | Visualization |
|--------|-----------|---------|---------------|
| Metrics | Prometheus scraping, Node Exporter, cAdvisor | Prometheus TSDB | Grafana |
| Logs | Promtail Docker discovery | Loki (label-indexed) | Grafana Explore |
| Traces | OTEL SDK → OTEL Collector | Jaeger (Badger) | Grafana + Jaeger UI |

---

## 🛠️ Technology Stack

| Component | Version | Role |
|---|---|---|
| FastAPI | 0.111+ | Observable demo application |
| Prometheus | v2.51.0 | Metrics collection & alerting engine |
| Grafana | v10.4.0 | Unified visualization & dashboards |
| Loki | v2.9.5 | Log aggregation (label-indexed) |
| Promtail | v2.9.5 | Log shipping agent (Docker discovery) |
| Jaeger | v1.56 | Distributed tracing backend & UI |
| OpenTelemetry Collector | v0.99.0 | Vendor-neutral telemetry pipeline |
| Alertmanager | v0.27.0 | Alert routing, deduplication, silencing |
| Node Exporter | v1.7.0 | Host metrics (CPU, memory, disk, network) |
| cAdvisor | v0.49.1 | Container resource metrics |
| Boto3 | Latest | AWS SNS alert delivery automation |

---

## 🚀 Quick Start

### Prerequisites
- Docker Engine 24+
- Docker Compose v2+
- 4 GB RAM minimum (8 GB recommended)
- Ports available: 3000, 3100, 4317, 8000, 8080, 9080, 9090, 9093, 9100, 16686

### 1. Clone and configure
```bash
git clone https://github.com/suyashdworkspace/observability-stack.git
cd observability-stack
cp .env.example .env
# Edit .env to set your Grafana admin password
```

### 2. Start the stack
```bash
docker compose up -d
```

### 3. Wait for initialization
```bash
sleep 30 && docker compose ps
```

### 4. Verify health
```bash
curl http://localhost:9090/-/healthy         # Prometheus
curl http://localhost:3100/ready             # Loki
curl http://localhost:8000/health            # Application
curl http://localhost:9093/-/healthy         # Alertmanager
```

---

## 🌐 Service URLs

| Service | URL | Credentials |
|---|---|---|
| **Grafana** | http://localhost:3000 | admin / (see .env) |
| **Prometheus** | http://localhost:9090 | — |
| **Alertmanager** | http://localhost:9093 | — |
| **Jaeger UI** | http://localhost:16686 | — |
| **cAdvisor** | http://localhost:8080 | — |
| **FastAPI Docs** | http://localhost:8000/docs | — |
| **Loki API** | http://localhost:3100 | — |
| **Promtail** | http://localhost:9080 | — |

---

## 📊 Key Dashboards

A pre-provisioned dashboard ("FastAPI Application Metrics") is auto-loaded into Grafana on startup from `grafana/dashboards/app-metrics.json`. It covers:

- HTTP request rate and error rate by endpoint/status
- P50 / P95 / P99 latency histograms
- Active connections gauge
- Business error rate by error type
- Container CPU and memory for the app service
- Log volume by level and a live log stream (via Loki)

You can additionally import the community **Node Exporter Full** dashboard (ID `1860`) for host-level CPU, memory, disk, and network panels.

---

## 🔔 Alert Rules

| Alert | Severity | Condition |
|---|---|---|
| ServiceDown | Critical | `up == 0` for 1m |
| HighErrorRate | Warning | HTTP 5xx rate > 5% for 2m |
| HighLatencyP99 | Warning | P99 > 2s for 3m |
| HighBusinessErrorRate | Warning | business error rate > 0.1/s for 5m |
| HighCPUUsage | Warning | CPU > 85% for 5m |
| HighMemoryUsage | Warning | Memory > 85% for 5m |
| DiskSpaceLow | Critical | Disk free < 15% for 10m |
| ContainerRestarting | Warning | >3 restarts in 15m |

> **Note on webhook receivers**: `alertmanager/alertmanager.yml` routes to `http://host.docker.internal:5001/...` placeholder webhooks. On Linux with Docker Engine (not Docker Desktop), add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `alertmanager` service in `docker-compose.yml`, or point the receivers at a real webhook endpoint (Slack, PagerDuty, etc.). See the Troubleshooting section below.

---

## 🤖 Automation Scripts

### Boto3 SNS Alert Integration
```bash
# Set up AWS credentials
aws configure

# Optional: configure alert email
export ALERT_EMAIL=your@email.com

# Run the automation script
cd scripts
python3 -m venv venv
source venv/bin/activate
pip install boto3 requests
python3 alertmanager_sns.py
deactivate
cd ..
```

**What it does:**
1. Creates/retrieves an AWS SNS topic (`observability-stack-alerts`)
2. Subscribes an email address for alert delivery
3. Queries live Alertmanager for firing alerts
4. Publishes formatted alert payloads to SNS
5. Reports a Prometheus firing-alert summary

This requires valid AWS credentials with SNS permissions (`sns:CreateTopic`, `sns:Subscribe`, `sns:Publish`, `sns:ListTopics`). It is safe to run against a sandbox/dev AWS account.

---

## 🧪 Load Testing

```bash
# Install hey (HTTP load generator)
wget -O /usr/local/bin/hey https://hey-release.s3.us-east-2.amazonaws.com/hey_linux_amd64
chmod +x /usr/local/bin/hey

# Generate normal traffic
hey -n 500 -c 20 http://localhost:8000/api/items

# Trigger slow requests
hey -n 50 -c 5 http://localhost:8000/api/slow

# Trigger error simulation
hey -n 100 -c 10 http://localhost:8000/api/error-simulation
```

---

## 📁 Project Structure

```
observability-stack/
├── app/                          # FastAPI application
│   ├── main.py                   # App with OTEL, Prometheus, JSON logging
│   ├── Dockerfile
│   └── requirements.txt
├── prometheus/
│   ├── prometheus.yml            # Scrape configs, alertmanager ref
│   └── rules/
│       └── alert_rules.yml       # PromQL-based alert rules
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/          # Auto-provisioned data sources
│   │   └── dashboards/           # Dashboard provider config
│   └── dashboards/               # Dashboard JSON files
├── loki/
│   └── loki-config.yml           # Loki storage and limits config
├── promtail/
│   └── promtail-config.yml       # Docker discovery + pipeline stages
├── alertmanager/
│   └── alertmanager.yml          # Routing, receivers, inhibition
├── otel-collector/
│   └── otel-collector-config.yml # Receivers, processors, exporters
├── scripts/
│   └── alertmanager_sns.py       # Boto3 AWS SNS automation
├── .github/
│   └── workflows/
│       └── observability-ci.yml  # CI: lint, build, scan, integration test
├── docker-compose.yml
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🔧 Configuration Reference

### Changing Scrape Intervals
Edit `prometheus/prometheus.yml`:
```yaml
global:
  scrape_interval: 15s  # Lower = more granular, higher = less load
```

### Adding a New Service to Monitor
1. Add the service to `docker-compose.yml` on the `observability` network
2. Add a `scrape_configs` entry to `prometheus/prometheus.yml`
3. Add `relabel_configs` to extract meaningful labels
4. Create a Grafana panel for the new service

### Enabling Slack Notifications
In `alertmanager/alertmanager.yml`, replace a webhook receiver with:
```yaml
receivers:
  - name: 'slack-critical'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
        channel: '#alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

---

## 🩺 Troubleshooting

A few of the most common first-run issues (see the full blueprint for the complete list):

- **Prometheus target `connection refused`**: check `docker compose logs app`; rebuild with `docker compose build app --no-cache` if a dependency is missing.
- **Loki "entry out of order"**: stop Promtail, clear its `positions.yaml`, and restart — usually caused by clock drift or stale offset tracking after a container restart.
- **No traces in Jaeger**: verify `OTEL_EXPORTER_OTLP_ENDPOINT` inside the app container and confirm `otel-collector` can reach `jaeger:14250`.
- **Alertmanager `no route to host` on webhook**: `host.docker.internal` doesn't resolve automatically on Linux + Docker Engine — add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `alertmanager` service.
- **Port already allocated**: another process owns the port; find it with `sudo lsof -i :<port>` and either stop it or remap the host-side port in `docker-compose.yml`.
- **cAdvisor permission denied on `/dev/kmsg`**: common on Docker Desktop; remove the `devices: [/dev/kmsg]` line from the `cadvisor` service if it won't start.

---

## 📖 Learning Outcomes

After building this project, you will have hands-on experience with:

- **Prometheus data model**: Understanding metric types, label cardinality, and PromQL functions
- **Log pipeline design**: Promtail stages for JSON parsing, label extraction, and log routing
- **Distributed tracing**: Span propagation, trace context, sampling strategies
- **Alerting engineering**: Writing alerts with appropriate `for` durations, severity routing, and inhibition rules
- **Cloud automation**: Boto3 resource management and event-driven notification patterns
- **Container observability**: cAdvisor metrics, Docker log driver configuration
- **CI/CD for infrastructure**: Validating Prometheus/Alertmanager configs in pipelines, security scanning

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/add-tempo-tracing`
3. Commit with conventional commits: `git commit -m "feat: add Grafana Tempo as tracing backend"`
4. Push and open a Pull Request

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built as a portfolio project demonstrating full-stack observability engineering with Docker Compose.*
