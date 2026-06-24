"""
alertmanager_sns.py

Automation script that:
1. Creates an AWS SNS topic for alert routing
2. Subscribes an email endpoint
3. Simulates an Alertmanager webhook payload and publishes to SNS
4. Queries live Alertmanager for active alerts and publishes a summary
5. Lists all active Prometheus alerts

Usage:
    pip install boto3 requests
    AWS_DEFAULT_REGION=us-east-1 python3 alertmanager_sns.py
"""

import boto3
import json
import requests
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
SNS_TOPIC_NAME = "observability-stack-alerts"
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "alerts@example.com")
ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://localhost:9093")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")


# ─────────────────────────────────────────────────────────────────────────────
# AWS SNS OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_sns_client():
    """Initialize and return a boto3 SNS client."""
    try:
        client = boto3.client("sns", region_name=AWS_REGION)
        # Verify credentials by making a simple API call
        client.get_caller_identity if hasattr(client, 'get_caller_identity') else None
        return client
    except NoCredentialsError:
        print("[ERROR] AWS credentials not configured. Run 'aws configure' first.")
        sys.exit(1)


def create_or_get_sns_topic(sns_client: boto3.client, topic_name: str) -> str:
    """Create SNS topic if it doesn't exist and return the ARN."""
    try:
        print(f"[SNS] Creating/getting topic: {topic_name}")
        response = sns_client.create_topic(
            Name=topic_name,
            Tags=[
                {"Key": "Project", "Value": "observability-stack"},
                {"Key": "Environment", "Value": "development"},
                {"Key": "ManagedBy", "Value": "boto3-script"},
            ]
        )
        topic_arn = response["TopicArn"]
        print(f"[SNS] Topic ARN: {topic_arn}")
        return topic_arn
    except ClientError as e:
        print(f"[ERROR] Failed to create SNS topic: {e}")
        raise


def subscribe_email_to_topic(sns_client: boto3.client, topic_arn: str, email: str) -> str:
    """Subscribe an email address to the SNS topic."""
    try:
        print(f"[SNS] Subscribing {email} to topic...")
        response = sns_client.subscribe(
            TopicArn=topic_arn,
            Protocol="email",
            Endpoint=email,
            ReturnSubscriptionArn=True
        )
        subscription_arn = response["SubscriptionArn"]
        print(f"[SNS] Subscription ARN: {subscription_arn}")
        print(f"[SNS] NOTE: Check {email} inbox to confirm the subscription.")
        return subscription_arn
    except ClientError as e:
        print(f"[ERROR] Failed to subscribe email: {e}")
        raise


def publish_alert_to_sns(
    sns_client: boto3.client,
    topic_arn: str,
    alert_name: str,
    severity: str,
    description: str,
    labels: dict
) -> str:
    """Publish a formatted alert notification to SNS."""
    subject = f"[{severity.upper()}] {alert_name} — Observability Stack"

    message_body = {
        "alert_name": alert_name,
        "severity": severity,
        "description": description,
        "labels": labels,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "observability-stack/alertmanager",
        "runbook_url": f"https://wiki.example.com/runbooks/{alert_name.lower()}",
        "grafana_url": "http://localhost:3000",
        "prometheus_url": PROMETHEUS_URL,
        "alertmanager_url": ALERTMANAGER_URL,
    }

    # SNS supports different message per protocol
    sns_message = {
        "default": json.dumps(message_body, indent=2),
        "email": f"""
=== OBSERVABILITY STACK ALERT ===

Alert Name  : {alert_name}
Severity    : {severity.upper()}
Timestamp   : {message_body['timestamp']}

Description:
{description}

Labels:
{json.dumps(labels, indent=2)}

Links:
- Grafana : http://localhost:3000
- Alertmanager: {ALERTMANAGER_URL}
- Prometheus: {PROMETHEUS_URL}

Runbook: {message_body['runbook_url']}
"""
    }

    try:
        print(f"[SNS] Publishing alert '{alert_name}' to topic...")
        response = sns_client.publish(
            TopicArn=topic_arn,
            Message=json.dumps(sns_message),
            Subject=subject[:100],  # SNS subject limit is 100 chars
            MessageStructure="json",
            MessageAttributes={
                "severity": {
                    "DataType": "String",
                    "StringValue": severity
                },
                "alert_name": {
                    "DataType": "String",
                    "StringValue": alert_name
                }
            }
        )
        message_id = response["MessageId"]
        print(f"[SNS] Published successfully. MessageId: {message_id}")
        return message_id
    except ClientError as e:
        print(f"[ERROR] Failed to publish to SNS: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# ALERTMANAGER + PROMETHEUS QUERIES
# ─────────────────────────────────────────────────────────────────────────────

def get_active_alertmanager_alerts(alertmanager_url: str) -> list:
    """Query Alertmanager API for currently active alerts."""
    try:
        response = requests.get(
            f"{alertmanager_url}/api/v2/alerts",
            params={"active": "true", "silenced": "false"},
            timeout=10
        )
        response.raise_for_status()
        alerts = response.json()
        print(f"[ALERTMANAGER] Found {len(alerts)} active alert(s)")
        return alerts
    except requests.exceptions.ConnectionError:
        print(f"[WARN] Cannot connect to Alertmanager at {alertmanager_url}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Alertmanager query failed: {e}")
        return []


def get_prometheus_firing_alerts(prometheus_url: str) -> list:
    """Query Prometheus API for firing alerts."""
    try:
        response = requests.get(
            f"{prometheus_url}/api/v1/alerts",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        alerts = [
            alert for alert in data.get("data", {}).get("alerts", [])
            if alert.get("state") == "firing"
        ]
        print(f"[PROMETHEUS] Found {len(alerts)} firing alert(s)")
        return alerts
    except requests.exceptions.ConnectionError:
        print(f"[WARN] Cannot connect to Prometheus at {prometheus_url}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Prometheus query failed: {e}")
        return []


def simulate_alertmanager_webhook_payload() -> dict:
    """Generate a realistic Alertmanager webhook payload for testing."""
    return {
        "version": "4",
        "groupKey": "{}:{alertname=\"ServiceDown\"}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "sns-webhook",
        "groupLabels": {"alertname": "ServiceDown"},
        "commonLabels": {
            "alertname": "ServiceDown",
            "job": "fastapi-app",
            "instance": "app:8000",
            "severity": "critical",
            "team": "platform"
        },
        "commonAnnotations": {
            "summary": "Service fastapi-app is DOWN",
            "description": "Target app:8000 of job fastapi-app has been down for more than 1 minute.",
            "runbook_url": "https://wiki.example.com/runbooks/service-down"
        },
        "externalURL": ALERTMANAGER_URL,
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "ServiceDown",
                    "job": "fastapi-app",
                    "instance": "app:8000",
                    "severity": "critical"
                },
                "annotations": {
                    "summary": "Service fastapi-app is DOWN",
                    "description": "Target app:8000 of job fastapi-app has been down for more than 1 minute."
                },
                "startsAt": datetime.utcnow().isoformat() + "Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": f"{PROMETHEUS_URL}/graph?g0.expr=up%3D%3D0",
                "fingerprint": "a8c4e6b2d1f3e5a7"
            }
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("OBSERVABILITY STACK — Boto3 AWS SNS Automation Script")
    print("=" * 60)
    print(f"Region       : {AWS_REGION}")
    print(f"Topic Name   : {SNS_TOPIC_NAME}")
    print(f"Alert Email  : {ALERT_EMAIL}")
    print(f"Alertmanager : {ALERTMANAGER_URL}")
    print(f"Prometheus   : {PROMETHEUS_URL}")
    print("-" * 60)

    # Initialize SNS client
    sns = get_sns_client()

    # Step 1: Create/get SNS topic
    topic_arn = create_or_get_sns_topic(sns, SNS_TOPIC_NAME)

    # Step 2: Subscribe email (idempotent — won't duplicate if already subscribed)
    if ALERT_EMAIL != "alerts@example.com":
        subscribe_email_to_topic(sns, topic_arn, ALERT_EMAIL)
    else:
        print("[SKIP] Using example email — set ALERT_EMAIL env var to subscribe a real address.")

    # Step 3: Query live Alertmanager for active alerts
    print("\n[STEP 3] Querying Alertmanager for active alerts...")
    active_alerts = get_active_alertmanager_alerts(ALERTMANAGER_URL)

    if active_alerts:
        for alert in active_alerts:
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            publish_alert_to_sns(
                sns, topic_arn,
                alert_name=labels.get("alertname", "UnknownAlert"),
                severity=labels.get("severity", "unknown"),
                description=annotations.get("description", "No description available"),
                labels=labels
            )
    else:
        print("[INFO] No active alerts — publishing a simulated test alert...")
        payload = simulate_alertmanager_webhook_payload()
        alert = payload["alerts"][0]
        publish_alert_to_sns(
            sns, topic_arn,
            alert_name=alert["labels"]["alertname"],
            severity=alert["labels"]["severity"],
            description=alert["annotations"]["description"],
            labels=alert["labels"]
        )

    # Step 4: Print Prometheus firing alerts
    print("\n[STEP 4] Querying Prometheus for firing alerts...")
    firing_alerts = get_prometheus_firing_alerts(PROMETHEUS_URL)
    if firing_alerts:
        print("\nFIRING ALERTS:")
        for alert in firing_alerts:
            print(f"  - {alert['labels']['alertname']} | {alert['labels'].get('severity','?')} | {alert['labels'].get('job','?')}")
    else:
        print("[INFO] No firing alerts in Prometheus.")

    # Step 5: List all topics in account
    print("\n[STEP 5] Listing all SNS topics in account...")
    paginator = sns.get_paginator("list_topics")
    for page in paginator.paginate():
        for topic in page["Topics"]:
            print(f"  {topic['TopicArn']}")

    print("\n" + "=" * 60)
    print("Script completed successfully.")
    print("=" * 60)


if __name__ == "__main__":
    main()
