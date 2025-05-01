Fraud Detection MLOps MVP on AWS – High‑Level Specification

1. Objective

Build a production‑style, event‑driven MVP that showcases end‑to‑end MLOps skills on AWS, centred on real‑time fraud detection using a publicly available credit‑card dataset.

⸻

2. Environments & Accounts

Environment	AWS Account	VPC CIDR	Promotion Flow
dev	<dev‑acct‑id>	10.0.0.0/24	Auto‑deploy on merge → unit tests → manual approval
stage	<stage‑acct‑id>	10.0.1.0/24	After dev pass & approval
prod	<prod‑acct‑id>	10.0.2.0/24	After stage pass & approval

Terraform workspaces map 1‑for‑1 to these accounts.

Tags applied to all resources:
	•	Project = fraud-detection
	•	Environment = dev|stage|prod

⸻

3. Data Set & Storage
	•	Source: Kaggle “Credit Card Fraud Detection” (284 807 rows, 492 frauds).
	•	Landing bucket: s3://fraud-detection-data/credit-card/ (versioning off).
	•	Splits: placeholders – current pipeline re‑uses the validation split for evaluation.

⸻

4. Event‑Driven Data Flow

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

4.1 SNS / SQS
	•	SNS FIFO topic → SQS FIFO queue (exactly‑once, ordered).
	•	DLQ: fraud-detection-dlq; maxReceiveCount = 3.

4.2 Lambda (Python 3.11, container)
	•	Image: built in GitHub Actions, pushed to ECR.Base: Amazon Linux 2 + pandas + scikit‑learn.
	•	Role: fraud-detection-lambda-role with:
	•	AWSLambdaBasicExecutionRole
	•	AmazonSQSReadOnlyAccess
	•	AmazonSageMakerInvokeEndpoint
	•	Env vars:
	•	SAGEMAKER_ENDPOINT_NAME = fraud-detection-endpoint
	•	AWS_REGION = us-east-1
	•	HIGH_AMOUNT_THRESHOLD = 0.99
	•	LOG_LEVEL = INFO
	•	Event source mapping: batch 5, reserved concurrency 5.
	•	Feature engineering (per message):
	1.	pass‐through V1–V28 (PCA)
	2.	standard‑scale Amount
	3.	derive hour_of_day
	4.	binary high_amount
	5.	interaction Amount × V12 (example)
	6.	TODO: time_since_last_tx (needs state)

4.3 SageMaker Endpoint
	•	Model: XGBoost binary classifier (built‑in container).
	•	Instance: ml.m5.large, autoscale 1 ↔ 3 based on CPU (<30 % / >60 %).
	•	Network: deployed in VPC private subnet with SG to allow Lambda → HTTPS.

⸻

5. SageMaker Pipeline (Training → Registration)

Step	Details
1 – Processing	Split/prepare dataset (placeholder split logic)
2 – Hyperparameter Tuning	Built‑in XGBoost; Bayesian search over max_depth, eta, subsample (placeholder ranges, 20 jobs, parallel 3) on ml.m5.xlarge.
3 – ModelEvaluation	Processing on ml.t3.medium (1) over validation set; emit ROC AUC, P@99 % Recall, F1, confusion; thresholds TBD.
4 – ManualApproval	Notifies SNS fraud-detection-model-approvals, IAM principal prod role can approve.
5 – RegisterModel	Registers best model as PendingApproval.
*6 – (Out‑of‑scope auto‑deploy)	Manual promotion deploys to endpoint.

Pipeline triggered by GitHub Actions on push → main (static AWS creds in repo secrets).

⸻

6. Networking & Security
	•	VPC: single‑AZ, /24, subdivided into three /26 (public, app‑private, data‑private).
	•	NAT GW: one per env (public subnet).
	•	Endpoints (core + ECR): S3 Gateway, Interface for SQS, SNS, DynamoDB, SageMaker (API & runtime), ECR (API & DKR).
	•	All traffic stays on AWS backbone; services without endpoints egress via NAT.
	•	Encryption: AWS‑managed SSE defaults.

⸻

7. CI/CD – GitHub Actions

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

	•	Promotion gates: unit tests pass + manual approval between envs.
	•	AWS auth: repo secrets AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (Admin privileges).

⸻

8. Monitoring & Alerting
	•	CloudWatch Alarms → SNS fraud-detection-alerts:
	•	Lambda error >1/min
	•	SQS depth >10 msgs/5 min
	•	Endpoint 4XX/5XX >1/min
	•	DLQ messages >0/min
	•	CloudWatch Dashboard (metrics placeholders – TBD).
	•	Model Monitor: high‑frequency schedule; alerts only.
	•	AWS Budgets: monthly fixed $50 per account → alerts topic.

⸻

9. State & Locking
	•	S3 bucket fraud-detection-tfstate with prefixes /dev/, /stage/, /prod/.
	•	DynamoDB lock tables: fraud-detection-tfstate-locks-dev|stage|prod (one per env).

⸻

10. Cost‑Optimisation Notes
	•	Single‑AZ & smallest feasible instance classes.
	•	VPC endpoints reduce NAT data charges.
	•	Autoscaling to min = 1 for endpoint; Lambda is pay‑per‑invocation.

⸻

11. Future TODOs / Placeholders
	1.	Define exact train/validation/test split & thresholds.
	2.	Complete time_since_last_tx feature with state store.
	3.	Flesh out CloudWatch Dashboard widgets.
	4.	Decide DynamoDB GSI & TTL for ad‑hoc queries and ageing.
	5.	Fill hyper‑parameter ranges & tuning job counts.
	6.	Add integration & load tests beyond unit scope.
	7.	Implement automated redeploy on Model Monitor drift (optional v2).

⸻

12. Deliverables
	•	Terraform root configuration (single‑module) + variables per workspace.
	•	GitHub Actions CI pipeline YAML.
	•	Lambda Dockerfile + handler code.
	•	SageMaker Pipeline definition (pipeline.py).
	•	Documentation (this spec + README with quick‑start & teardown).

⸻

## Architecture
[<img src="./docs/architecture.png"/>](./docs/arch-diagram.png)
[![](./docs/architecture.svg)](./docs/arch-diagram.svg)
