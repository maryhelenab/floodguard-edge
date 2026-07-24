"""Shared pytest configuration for FloodGuard tests."""

import os

import boto3
import pytest
from moto import mock_aws


# Fake credentials used only by moto and boto3 during tests.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def dynamodb_table(request):
    """Create the mocked DynamoDB table used by Lambda tests."""

    table_name = request.module.TABLE_NAME

    with mock_aws():
        dynamodb = boto3.resource(
            "dynamodb",
            region_name="us-east-1",
        )

        table = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        table.wait_until_exists()
        yield table
