"""
SageMaker Pipeline definition for training, tuning, and registering the fraud detection model.
"""

import logging
import os

import boto3
import sagemaker
from sagemaker.inputs import TrainingInput
from sagemaker.model_metrics import MetricsSource, ModelMetrics
from sagemaker.processing import ProcessingInput, ProcessingOutput, ScriptProcessor
from sagemaker.sklearn.processing import SKLearnProcessor
from sagemaker.tuner import ContinuousParameter, HyperparameterTuner, IntegerParameter
from sagemaker.workflow.parameters import ParameterInteger, ParameterString
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.step_collections import RegisterModel
from sagemaker.workflow.steps import CacheConfig, ProcessingStep, TuningStep

logger = logging.getLogger(__name__)


def get_sagemaker_client(region: str | None = None) -> boto3.client:
    """
    Get the SageMaker client.
    
    Args:
        region: The AWS region to create the client in.
        
    Returns:
        The SageMaker client.
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("sagemaker", region_name=region)


def get_sagemaker_runtime_client(region: str | None = None) -> boto3.client:
    """
    Get the SageMaker runtime client.
    
    Args:
        region: The AWS region to create the client in.
        
    Returns:
        The SageMaker runtime client.
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("sagemaker-runtime", region_name=region)


def get_pipeline(
    region: str,
    role: str,
    pipeline_name: str,
    model_package_group_name: str,
    base_job_prefix: str,
    processing_instance_type: str = "ml.m5.xlarge",
    training_instance_type: str = "ml.m5.xlarge",
) -> Pipeline:
    """
    Get the SageMaker Pipeline instance.
    
    Args:
        region: The AWS region to create the pipeline in.
        role: The IAM role to use for the pipeline.
        pipeline_name: The name of the pipeline.
        model_package_group_name: The name of the model package group.
        base_job_prefix: The prefix for the job names.
        processing_instance_type: The instance type for processing jobs.
        training_instance_type: The instance type for training jobs.
        
    Returns:
        The SageMaker Pipeline instance.
    """
    sagemaker_session = sagemaker.session.Session(
        boto_session=boto3.session.Session(region_name=region)
    )
    
    # Define pipeline parameters
    processing_instance_count = ParameterInteger(
        name="ProcessingInstanceCount", default_value=1
    )
    
    model_approval_status = ParameterString(
        name="ModelApprovalStatus", default_value="PendingManualApproval"
    )
    
    input_data = ParameterString(
        name="InputDataUrl",
        default_value="s3://fraud-detection-data/credit-card/creditcard.csv",
    )
    
    # Cache config for processing and training steps
    cache_config = CacheConfig(enable_caching=True, expire_after="30d")
    
    # Processing step for feature engineering and data splitting
    sklearn_processor = SKLearnProcessor(
        framework_version="1.0-1",
        role=role,
        instance_type=processing_instance_type,
        instance_count=processing_instance_count,
        base_job_name=f"{base_job_prefix}/sklearn-fraud-process",
        sagemaker_session=sagemaker_session,
    )
    
    processing_step = ProcessingStep(
        name="PreprocessFraudData",
        processor=sklearn_processor,
        inputs=[
            ProcessingInput(
                source=input_data,
                destination="/opt/ml/processing/input",
            ),
        ],
        outputs=[
            ProcessingOutput(output_name="train", source="/opt/ml/processing/train"),
            ProcessingOutput(output_name="validation", source="/opt/ml/processing/validation"),
            ProcessingOutput(output_name="test", source="/opt/ml/processing/test"),
        ],
        code="fraud_detection/processing/preprocessing.py",
        cache_config=cache_config,
    )
    
    # Hyperparameter tuning step
    xgb_train = sagemaker.estimator.Estimator(
        image_uri=sagemaker.image_uris.retrieve(
            framework="xgboost",
            region=region,
            version="1.5-1",
            py_version="py3",
            instance_type=training_instance_type,
        ),
        role=role,
        instance_count=1,
        instance_type=training_instance_type,
        output_path=f"s3://{sagemaker_session.default_bucket()}/{base_job_prefix}/xgboost-fraud-train-output",
        sagemaker_session=sagemaker_session,
        base_job_name=f"{base_job_prefix}/xgboost-fraud-train",
    )
    
    # Set hyperparameters
    xgb_train.set_hyperparameters(
        objective="binary:logistic",
        num_round=100,
        eval_metric="auc",
        use_bias=True,
    )
    
    # Define hyperparameter ranges for tuning
    hyperparameter_ranges = {
        "max_depth": IntegerParameter(3, 10),
        "eta": ContinuousParameter(0.01, 0.3),
        "subsample": ContinuousParameter(0.5, 1.0),
    }
    
    # Define metric to optimize
    objective_metric_name = "validation:auc"
    
    # Create the tuner
    tuner = HyperparameterTuner(
        xgb_train,
        objective_metric_name,
        hyperparameter_ranges,
        max_jobs=20,
        max_parallel_jobs=3,
        strategy="Bayesian",
        objective_type="Maximize",
    )
    
    # Create the tuning step
    tuning_step = TuningStep(
        name="TuneFraudModel",
        tuner=tuner,
        inputs={
            "train": TrainingInput(
                s3_data=processing_step.properties.ProcessingOutputConfig.Outputs[
                    "train"
                ].S3Output.S3Uri,
                content_type="text/csv",
            ),
            "validation": TrainingInput(
                s3_data=processing_step.properties.ProcessingOutputConfig.Outputs[
                    "validation"
                ].S3Output.S3Uri,
                content_type="text/csv",
            ),
        },
        cache_config=cache_config,
    )
    
    # Model evaluation step
    evaluation_processor = ScriptProcessor(
        image_uri=sagemaker.image_uris.retrieve(
            framework="sklearn",
            region=region,
            version="1.0-1",
            py_version="py3",
            instance_type=processing_instance_type,
        ),
        role=role,
        instance_count=1,
        instance_type=processing_instance_type,
        base_job_name=f"{base_job_prefix}/fraud-model-evaluation",
        sagemaker_session=sagemaker_session,
    )
    
    evaluation_report = PropertyFile(
        name="EvaluationReport",
        output_name="evaluation",
        path="evaluation.json",
    )
    
    evaluation_step = ProcessingStep(
        name="EvaluateFraudModel",
        processor=evaluation_processor,
        inputs=[
            ProcessingInput(
                source=tuning_step.get_top_model_s3_uri(
                    top_k=0,
                    s3_bucket=sagemaker_session.default_bucket(),
                    prefix=f"{base_job_prefix}/TuneFraudModel",
                ),
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=processing_step.properties.ProcessingOutputConfig.Outputs[
                    "test"
                ].S3Output.S3Uri,
                destination="/opt/ml/processing/test",
            ),
        ],
        outputs=[
            ProcessingOutput(
                output_name="evaluation",
                source="/opt/ml/processing/evaluation",
            ),
        ],
        code="fraud_detection/processing/evaluate.py",
        property_files=[evaluation_report],
        cache_config=cache_config,
    )
    
    # Register model step conditionally based on model quality
    model_metrics = ModelMetrics(
        model_statistics=MetricsSource(
            s3_uri=f"{evaluation_step.arguments['ProcessingOutputConfig']['Outputs'][0]['S3Output']['S3Uri']}/evaluation.json",
            content_type="application/json",
        )
    )
    
    register_step = RegisterModel(
        name="RegisterFraudModel",
        estimator=xgb_train,
        model_data=tuning_step.get_top_model_s3_uri(
            top_k=0,
            s3_bucket=sagemaker_session.default_bucket(),
            prefix=f"{base_job_prefix}/TuneFraudModel",
        ),
        content_types=["text/csv"],
        response_types=["application/json"],
        inference_instances=["ml.m5.large", "ml.m5.xlarge"],
        transform_instances=["ml.m5.xlarge"],
        model_package_group_name=model_package_group_name,
        approval_status=model_approval_status,
        model_metrics=model_metrics,
    )
    
    # Create the pipeline
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            processing_instance_count,
            model_approval_status,
            input_data,
        ],
        steps=[
            processing_step,
            tuning_step,
            evaluation_step,
            register_step,
        ],
        sagemaker_session=sagemaker_session,
    )
    
    return pipeline


def run_pipeline(
    pipeline_name: str,
    parameters: dict[str, str] | None = None,
    region: str | None = None,
) -> dict[str, str]:
    """
    Run the pipeline with the given parameters.
    
    Args:
        pipeline_name: The name of the pipeline to run.
        parameters: The parameters to pass to the pipeline.
        region: The AWS region where the pipeline is defined.
        
    Returns:
        The response from starting the pipeline execution.
    """
    sagemaker_client = get_sagemaker_client(region)
    
    response = sagemaker_client.start_pipeline_execution(
        PipelineName=pipeline_name,
        PipelineParameters=[
            {"Name": key, "Value": value} for key, value in (parameters or {}).items()
        ],
    )
    
    return response 