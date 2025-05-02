"""
Lambda function for fraud detection.

This function processes incoming credit card transaction events,
performs feature engineering, and calls the SageMaker endpoint
for real-time fraud detection.
"""

import json
import logging
import os
from typing import Any

import boto3

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients
sagemaker_runtime = boto3.client("sagemaker-runtime")
dynamodb = boto3.resource("dynamodb")

# Constants
ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE_NAME")


def preprocess_transaction(transaction: dict[str, Any]) -> dict[str, list[float]]:
    """
    Preprocess transaction data for model input.
    
    Args:
        transaction: Raw transaction data from the event
        
    Returns:
        Preprocessed features ready for model inference
    """
    # Extract features from transaction
    features = {}
    
    # TODO: Implement actual feature engineering as per spec:
    # 1. pass-through V1-V28 (PCA)
    # 2. standard-scale Amount
    # 3. derive hour_of_day
    # 4. binary high_amount
    # 5. interaction Amount x V12
    
    # Mock implementation for scaffolding
    features = {
        "features": [
            float(transaction.get(f"V{i}", 0)) for i in range(1, 29)
        ] + [
            float(transaction.get("Amount", 0)),
            float(transaction.get("hour_of_day", 0)),
            1.0 if float(transaction.get("Amount", 0)) > 100 else 0.0,
            float(transaction.get("Amount", 0)) * float(transaction.get("V12", 0))
        ]
    }
    
    return features


def invoke_endpoint(features: dict[str, list[float]]) -> dict[str, Any]:
    """
    Invoke SageMaker endpoint with preprocessed features.
    
    Args:
        features: Preprocessed features for model input
        
    Returns:
        Model prediction response
    """
    if not ENDPOINT_NAME:
        logger.error("SageMaker endpoint name not configured")
        raise ValueError("SAGEMAKER_ENDPOINT_NAME environment variable not set")
    
    try:
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=ENDPOINT_NAME,
            ContentType="application/json",
            Body=json.dumps(features)
        )
        
        result = json.loads(response["Body"].read().decode())
        return result
    
    except Exception as e:
        logger.error(f"Error invoking endpoint: {e!s}")
        raise


def save_result(transaction_id: str, prediction: dict[str, Any]) -> None:
    """
    Save prediction result to DynamoDB.
    
    Args:
        transaction_id: Unique ID for the transaction
        prediction: Model prediction result
    """
    if not DYNAMODB_TABLE:
        logger.error("DynamoDB table name not configured")
        raise ValueError("DYNAMODB_TABLE_NAME environment variable not set")
    
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        table.put_item(
            Item={
                "transaction_id": transaction_id,
                "is_fraud": prediction.get("is_fraud", False),
                "fraud_probability": prediction.get("probability", 0.0),
                "timestamp": prediction.get("timestamp", "")
            }
        )
    except Exception as e:
        logger.error(f"Error saving to DynamoDB: {e!s}")
        raise


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler function for processing SQS events containing credit card transactions.
    
    Args:
        event: AWS Lambda event object containing SQS records
        context: AWS Lambda context object
        
    Returns:
        Response object with processing results
    """
    logger.info("Received event: %s", json.dumps(event))
    
    results = []
    
    # Process SQS records
    for record in event.get("Records", []):
        try:
            # Parse message from SQS
            message_body = json.loads(record["body"])
            transaction = message_body.get("transaction", {})
            transaction_id = transaction.get("id")
            
            if not transaction_id:
                logger.warning("Transaction ID not found in message")
                continue
            
            # Preprocess transaction
            features = preprocess_transaction(transaction)
            
            # Invoke SageMaker endpoint
            prediction = invoke_endpoint(features)
            
            # Save result to DynamoDB
            save_result(transaction_id, prediction)
            
            results.append({
                "transaction_id": transaction_id,
                "is_fraud": prediction.get("is_fraud", False),
                "status": "processed"
            })
            
        except Exception as e:
            logger.error(f"Error processing record: {e!s}")
            results.append({
                "transaction_id": transaction.get("id", "unknown"),
                "status": "error",
                "error": str(e)
            })
    
    return {
        "statusCode": 200,
        "body": json.dumps({"results": results})
    } 