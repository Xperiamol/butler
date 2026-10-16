"""批量生成资料用的词表和小工具。内容是合成的、虚构公司 Tidepool Pay 的；不含任何真实公司或个人信息。"""
from __future__ import annotations
import random
import time

SERVICES = ["payment-service", "ledger-service", "auth-service", "notification-service", "fraud-engine", "settlement-service", "risk-scorer",
            "kyc-service", "reporting-service", "api-gateway", "merchant-portal", "card-issuer", "fx-service", "webhook-dispatcher", "billing-service",
            "profile-service", "search-service", "recon-service", "payout-service", "token-vault", "ratelimiter", "config-service", "scheduler", "export-service"]
TECH = ["PostgreSQL 15", "Aurora PostgreSQL", "Kafka", "Redis", "Kubernetes", "Terraform", "Datadog", "Grafana", "PagerDuty", "Okta", "Envoy", "gRPC",
        "OpenTelemetry", "Argo CD", "Vault", "S3", "SQS", "DynamoDB", "Flink", "dbt", "Airflow", "Snowflake", "Prometheus", "Loki", "Istio"]
FEATURES = ["multi-currency wallets", "instant payouts", "merchant onboarding v2", "3-D Secure 2 flows", "recurring billing", "split payments", "refund automation",
            "PayNow QR collection", "virtual cards", "chargeback evidence portal", "bulk disbursement API", "risk-based step-up auth", "settlement reports v3",
            "webhook replay", "sandbox data seeding", "idempotency keys for payouts", "dynamic currency conversion", "merchant analytics dashboard"]
SYMPTOMS = ["elevated p99 latency", "5xx spike on the checkout endpoint", "consumer lag on the settlement topic", "connection pool exhaustion", "stuck payout batches",
            "duplicate webhook deliveries", "memory growth after deploy", "intermittent TLS handshake failures", "cache stampede on merchant config", "slow queries on the ledger table",
            "token refresh failures", "DNS resolution timeouts", "certificate expiry warnings", "disk pressure on Kafka brokers", "retry storms after a downstream blip"]
CAUSES = ["a connection pool limit that was too low after the last release", "a missing index introduced by a schema migration", "an expired internal certificate",
          "an unbounded retry loop in the client library", "a noisy neighbour on a shared node pool", "a misconfigured autoscaling threshold", "a stale feature flag",
          "a hot partition caused by a skewed merchant id", "a long-running transaction holding row locks", "an upstream rate limit that was lowered without notice"]
FIXES = ["raised the pool size and added a saturation alert", "added the missing index concurrently during low traffic", "rotated the certificate and added expiry monitoring",
         "capped retries with exponential backoff and jitter", "moved the workload to a dedicated node pool", "tuned the HPA target and added a minimum replica count",
         "removed the flag and added a cleanup ticket", "salted the partition key", "split the transaction and added a statement timeout", "agreed a new limit with the provider and cached responses"]
TOPICS_POLICY = ["Acceptable use of company devices", "Password and MFA standards", "Data classification and handling", "Vendor risk assessment", "Incident severity definitions",
                 "On-call compensation", "Change management", "Access reviews", "Remote work and travel", "Expense reimbursement", "Source code retention", "Customer data requests"]
HOWTO = ["rotate a database credential", "roll back a Helm release", "add a new merchant webhook endpoint", "run a load test in staging", "request production access",
         "add a Grafana alert", "backfill a Kafka topic", "restore a table from a snapshot", "debug a stuck payout batch", "onboard a new service to the gateway",
         "generate a settlement report", "reproduce a customer-reported issue", "cut a release branch", "rotate TLS certificates"]
TEAM_TOPICS = {"payments-eng": ["settlement", "payouts", "refunds", "ledger"], "platform-eng": ["gateway", "service mesh", "CI/CD", "developer tooling"],
               "auth-eng": ["token service", "SSO", "MFA", "session management"], "data-eng": ["warehouse", "pipelines", "dbt models", "data quality"],
               "mobile-eng": ["iOS wallet", "Android wallet", "push notifications", "app release"], "sre": ["on-call", "capacity", "error budgets", "chaos testing"],
               "security": ["threat modelling", "pen-test findings", "secrets scanning", "access reviews"], "product": ["roadmap", "pricing", "merchant research", "launch plan"],
               "design": ["design system", "checkout UX", "accessibility", "research synthesis"], "finance": ["month-end close", "forecast", "vendor spend", "audit prep"],
               "legal": ["contract review", "regulatory filings", "privacy", "licensing"], "people-ops": ["hiring plan", "performance cycle", "onboarding", "benefits"],
               "support": ["ticket trends", "macros", "escalations", "knowledge base"], "sales": ["pipeline", "enablement", "renewals", "partner deals"],
               "compliance": ["MAS notices", "PCI DSS", "SOC 2 evidence", "AML monitoring"], "leadership": ["quarterly goals", "hiring", "budget", "strategy"]}
CHANNEL_WORDS = ["deploys", "alerts", "reviews", "help", "standup", "retro", "oncall", "design", "planning", "bugs", "releases", "data", "infra", "docs", "launch", "metrics", "sync", "social", "kudos", "ideas"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
STATUSES = ["To Do", "In Progress", "In Review", "Done", "Done", "Done", "Blocked"]
PRIORITIES = ["Low", "Medium", "Medium", "High", "Highest"]


def when(epoch: float, days_ago: float) -> float:
    return epoch - days_ago * 86400.0


def date(ts: float) -> str:
    t = time.gmtime(ts)
    return f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}"


def stamp(ts: float) -> str:
    t = time.gmtime(ts)
    return f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d} UTC"


class Pick:
    """带确定性随机数的取样器。"""

    def __init__(self, seed: int):
        self.r = random.Random(seed)

    def one(self, seq):
        return seq[self.r.randrange(len(seq))]

    def some(self, seq, k: int):
        return self.r.sample(list(seq), min(k, len(seq)))

    def chance(self, p: float) -> bool:
        return self.r.random() < p

    def between(self, a: float, b: float) -> float:
        return a + (b - a) * self.r.random()

    def int(self, a: int, b: int) -> int:
        return self.r.randint(a, b)
