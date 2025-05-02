# Fraud Detection MLOps MVP on AWS – High‑Level Specification

## 1. Objective

Build a production‑style, event‑driven MVP that showcases end‑to‑end MLOps skills on AWS, centred on real‑time fraud detection using a publicly available credit‑card dataset.
### Assumptions:
The design assumes moderate demo traffic (hundreds of events per minute), tight personal budget (< USD 50/mo per environment),
and the need to demonstrate best‑practice DevOps patterns (IaC, CI/CD, tagging, monitoring) without incurring the full complexity of enterprise security or compliance frameworks.
All AWS resources are created in us‑east‑1, and the primary audience is a hiring manager assessing MLOps proficiency rather than an operations team running a 24×7 service.
---

## 2. Environments & Accounts

| Environment | AWS Account     | VPC CIDR     | Promotion Flow                                      |
|------------|------------------|--------------|-----------------------------------------------------|
| dev        | <dev‑acct‑id>    | 10.0.0.0/24  | Auto‑deploy on merge → unit tests → manual approval |
| stage      | <stage‑acct‑id>  | 10.0.1.0/24  | After dev pass & approval                           |
| prod       | <prod‑acct‑id>   | 10.0.2.0/24  | After stage pass & approval                         |

Terraform workspaces map 1‑for‑1 to these accounts.

**Tags applied to all resources:**
- Project = `fraud-detection`
- Environment = `dev` | `stage` | `prod`

## Reasoning:
Three separate AWS accounts give hard isolation and clean cost attribution,
mirroring real‑world SDLC (Software Development Life Cycle) stages.
Using simple /24 CIDRs prevents overlap while keeping subnet maths trivial.
A minimal tag set still unlocks Cost Explorer filtering and satisfies most tagging policies without extra overhead.
---

## 3. Data Set & Storage

- **Source:** Kaggle “Credit Card Fraud Detection” (284,807 rows, 492 frauds).
- **Landing bucket:** `s3://fraud-detection-data/credit-card/` (versioning off).
- **Splits:** The current pipeline re‑uses the validation split for evaluation.

### Reasoning:
The Kaggle dataset is well‑known, license‑friendly,
and small enough
to train quickly on free SageMaker quota while being sufficiently imbalanced to showcase metric selection and tuning.
---

## 4. Event‑Driven Data Flow

```mermaid
flowchart LR
    subgraph Ingestion
        A[Local Python generator]
        SNS(SNS FIFO topic fraud-detection)
        SQS(SQS FIFO queue fraud-detection-queue)
    end
    subgraph Processing
        L[Lambda (container)]
        SM[SageMaker real‑time endpoint]
    end
    DB[(DynamoDB fraud-flag table)]
    A --> SNS --> SQS --> L --> SM --> L --> DB
```

- SNS / SQS
	-	SNS FIFO topic → SQS FIFO queue (exactly‑once, ordered).
	-	DLQ: fraud-detection-dlq; maxReceiveCount = 3.
- Lambda (Python 3.11, container)
	- Image: built in GitHub Actions, pushed to ECR.
    - Base: Amazon Linux 2 + pandas + scikit‑learn.
	- Role: fraud-detection-lambda-role with:
    - IAM permissions:
      1. AWSLambdaBasicExecutionRole
      2. AmazonSQSReadOnlyAccess
      3. AmazonSageMakerInvokeEndpoint
	- Event source mapping: batch = 5, reserved concurrency = 5.
    - Feature engineering (per message):
      1. pass‐through V1–V28 (PCA)
      2.	standard‑scale Amount
      3.	derive hour_of_day
      4.	binary high_amount
      5.	interaction Amount × V12 (example)
      6.	TODO: time_since_last_tx (needs state)
- SageMaker Endpoint
	-	Model: XGBoost binary classifier (built‑in container).
	-	Instance: ml.m5.large, autoscale 1 ↔ 3 based on CPU (<30 % / >60 %).
	-	Network: deployed in VPC private subnet with SG to allow Lambda → HTTPS.

### Reasoning:
FIFO semantics guarantee order and deduplication—important when unit‑testing a small dataset—while a DLQ
(Dead-Letter Queue) simplifies troubleshooting without losing data.
⸻

## 5. SageMaker Pipeline (Training → Registration)

| Step | Details |
|------|---------|
| 1 Processing | Split/prepare dataset (placeholder split logic) |
| 2 Hyperparameter Tuning | Built-in XGBoost; Bayesian search over `max_depth`, `eta`, `subsample` (placeholder ranges, 20 jobs, parallel 3) on **ml.m5.xlarge** |
| 3 Model Evaluation | Processing on **ml.t3.medium** (1) over validation set; emit ROC AUC, P@99 % Recall, F1, confusion; thresholds TBD |
| 4 Manual Approval | Notifies SNS **fraud-detection-model-approvals**; IAM principal **prod** role can approve |
| 5 Register Model | Registers best model as *PendingApproval* |
| 6 (Out-of-scope auto-deploy) | Manual promotion deploys to endpoint |

Pipeline triggered by GitHub Actions on push → main (static AWS creds in repo secrets).

### Reasoning:
A tuning job with Bayesian search highlights automated model selection skills,
while ManualApproval mimics a real governance flow without forcing automated promotion.

⸻

## 6. Networking & Security
  -	VPC: single‑AZ, /24, subdivided into three /26 (public, app‑private, data‑private).
  -	NAT GW: one per env (public subnet).
  -	Endpoints (core + ECR): S3 Gateway, Interface for SQS, SNS, DynamoDB, SageMaker (API & runtime), ECR (API & DKR).
  -	All traffic stays on AWS backbone; services without endpoints egress via NAT.
  -	Encryption: AWS‑managed SSE defaults.

### Reasoning:
Single Availability Zone (Single‑AZ)
plus endpoints avoids multi‑AZ NAT duplication costs yet keeps traffic on the AWS backbone,
demonstrating cost‑aware architecture choices suitable for a demo.
⸻

## 7. CI/CD–GitHub Actions
```yaml
on:
  push:
    branches: [main]
jobs:
  build-test:
    steps:
      - checkout
      - docker build && docker push (Lambda image)
      - run unit tests inside image
      - terraform init & plan (dev)
      - terraform apply (dev)
      - trigger SageMaker Pipeline (dev)
      - manual_approval_gate
      - repeat for stage, prod

	-	Promotion gates: unit tests pass + manual approval between envs.
	-	AWS auth: repo secrets AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (Admin privileges).
```

### Reasoning:
A one‑stop workflow is easier for reviewers to inspect,
and static Admin creds reduce OIDC setup time (an acceptable risk in disposable demo accounts).
⸻

## 8. Monitoring & Alerting
  -	CloudWatch Alarms → SNS fraud-detection-alerts:
  -	Lambda error >1/min
  -	SQS depth >10 msgs/5 min
  -	Endpoint 4XX/5XX >1/min
  -	DLQ messages >0/min
  -	CloudWatch Dashboard (metrics placeholders – TBD).
  -	Model Monitor: high‑frequency schedule; alerts only.
  -	AWS Budgets: monthly fixed $50 per account → alerts topic.
## Reasoning:
The chosen alarms map directly to common failure modes
(code errors, queue backlog, model endpoint faults) and feed one topic,
simplifying alert routing.
⸻

## 9. State & Locking
  -	S3 bucket fraud-detection-tfstate with prefixes /dev/, /stage/, /prod/.
  -	DynamoDB lock tables: fraud-detection-tfstate-locks-dev|stage|prod (one per env).
### Reasoning:
 Centralised state per bucket plus env‑specific lock tables avoid cross‑account read permissions
 while preserving a single source of truth for Terraform.
⸻

## 10. Cost‑Optimisation Notes
  -	Single‑AZ & smallest feasible instance classes.
  -	VPC endpoints reduce NAT data charges.
  -	Autoscaling to min = 1 for endpoint
  - Lambda is pay‑per‑invocation.
⸻

## 11. Future TODOs / Placeholders
1.	Define exact train/validation/test split & thresholds.
2.	Complete time_since_last_tx feature with state store.
3.	Flesh out CloudWatch Dashboard widgets.
4.	Decide DynamoDB GSI & TTL for ad‑hoc queries and ageing.
5.	Fill hyper‑parameter ranges & tuning job counts.
6.	Add integration & load tests beyond unit scope.
7.	Implement automated redeploy on Model Monitor drift (optional v2).

⸻

## 12. Deliverables
  -	Terraform root configuration (single‑module) + variables per workspace.
  -	GitHub Actions CI pipeline YAML.
  -	Lambda Dockerfile + handler code.
  -	SageMaker Pipeline definition (pipeline.py).
  -	Documentation (this spec + README with quick‑start & teardown).

⸻

## Architecture
[<img src="./arch-diagram.png"/>](./docs/arch-diagram.png)
