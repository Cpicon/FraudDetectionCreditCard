"""
Main module for testing the lambda handler locally.
"""

import json
import sys
from pathlib import Path

from fraud_detection.inference.lambda_handler import lambda_handler


def main():
    """
    Test the lambda handler with a sample event.
    
    Usage:
        python -m fraud_detection.inference [event_file.json]
    """
    # Create a sample event if no file provided
    if len(sys.argv) > 1:
        event_file = Path(sys.argv[1])
        with open(event_file) as f:
            event = json.load(f)
    else:
        # Sample event mimicking SQS
        event = {
            "Records": [
                {
                    "body": json.dumps({
                        "transaction": {
                            "id": "test-transaction-001",
                            "Amount": 123.45,
                            "V1": -1.3598071336738,
                            "V2": -0.0727811733098497,
                            "V3": 2.53634674,
                            "V4": 1.37815522,
                            "V5": -0.338320769942129,
                            "V6": 0.462387777762292,
                            "V7": 0.239598554061257,
                            "V8": 0.0986979012610507,
                            "V9": 0.363786969611213,
                            "V10": 0.0907941719789316,
                            "V11": -0.551599533260813,
                            "V12": -0.617800855762348,
                            "hour_of_day": 14,
                        }
                    })
                }
            ]
        }
    
    # Set mock environment variables
    import os
    os.environ["SAGEMAKER_ENDPOINT_NAME"] = "mock-endpoint"
    os.environ["DYNAMODB_TABLE_NAME"] = "mock-table"
    
    # Mock the SageMaker endpoint invocation
    import io
    
    # Create a mock SageMaker client
    class MockSageMakerRuntime:
        def invoke_endpoint(self, **kwargs):
            return {
                "Body": io.BytesIO(json.dumps({
                    "is_fraud": False,
                    "probability": 0.013,
                    "timestamp": "2023-01-01T14:00:00Z"
                }).encode())
            }
    
    # Create a mock DynamoDB table
    class MockTable:
        def put_item(self, **kwargs):
            print(f"Saved to DynamoDB: {kwargs['Item']}")
            return {}
    
    class MockDynamoDB:
        def Table(self, name):
            return MockTable()
    
    # Patch the boto3 clients
    import fraud_detection.inference.lambda_handler as lh
    lh.sagemaker_runtime = MockSageMakerRuntime()
    lh.dynamodb = MockDynamoDB()
    
    # Invoke the handler
    print(f"Invoking lambda_handler with event: {json.dumps(event, indent=2)}")
    result = lambda_handler(event, {})
    print(f"\nResult: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main() 