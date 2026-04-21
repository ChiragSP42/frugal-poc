import json
import os
import boto3
from collections import defaultdict
from boto3.dynamodb.conditions import Key

TXN_TABLE_NAME = os.getenv("TXN_TABLE_NAME")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TXN_TABLE_NAME) #type: ignore


def lambda_handler(event, context):
    user_id = event.get("userId")

    if not user_id:
        return {"statusCode": 400, "body": json.dumps({"error": "userId is required"})}

    # 1. Query all transactions for the user (userId is PK, transactionId is SK)
    response = table.query(
        KeyConditionExpression=Key("userId").eq(user_id)
    )
    transactions = response["Items"]

    # Handle DynamoDB pagination
    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=Key("userId").eq(user_id),
            ExclusiveStartKey=response["LastEvaluatedKey"]
        )
        transactions.extend(response["Items"])

    # 2. Aggregate amounts by pocCategory
    category_totals = defaultdict(float)
    for txn in transactions:
        category = txn.get("pocCategory")
        amount = txn.get("amount")
        if category and amount is not None:
            category_totals[category] += float(amount)

    # 3. Sort and return top 5 categories
    top_5 = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "statusCode": 200,
        "body": json.dumps({
            "userId": user_id,
            "topCategories": [
                {"category": cat, "totalAmount": round(amt, 2)}
                for cat, amt in top_5
            ]
        })
    }
