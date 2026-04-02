import json
import boto3
import datetime
import os
from boto3.dynamodb.conditions import Attr

# --- CONFIGURATION ---
MAIN_TABLE_NAME = os.getenv("MAIN_TABLE_NAME")
TXN_ANALYTICS_LAMBDA_NAME = os.getenv("TXN_ANALYTICS_LAMBDA_NAME")

dynamodb = boto3.resource('dynamodb')
main_table = dynamodb.Table(MAIN_TABLE_NAME)  # type: ignore

# Lambda client used to fan-out async invocations to transaction-analytics-lambda
lambda_client = boto3.client('lambda', region_name='us-east-1')


def get_all_user_ids() -> list[str]:
    """
    Scans the Main DynamoDB table for all items where SK begins with 'ACCOUNT#'.
    Extracts and deduplicates the userId from each item's PK ('USER#{userId}').

    This mirrors how transaction_analytics.py queries accounts — same table,
    same PK/SK structure — but here we need ALL users, not just one.

    Uses paginated Scan with LastEvaluatedKey to handle tables larger than 1MB.
    ProjectionExpression limits reads to only the PK attribute (cost optimization).
    """
    user_ids: set[str] = set()

    scan_kwargs: dict = {
        'FilterExpression': Attr('SK').begins_with('ACCOUNT#'),
        'ProjectionExpression': 'PK'
    }

    while True:
        response = main_table.scan(**scan_kwargs)

        for item in response.get('Items', []):
            pk: str = item.get('PK', '')
            if pk.startswith('USER#'):
                user_ids.add(pk[len('USER#'):])  # strip 'USER#' prefix

        # DynamoDB paginates at 1MB. Keep scanning until there's no more pages.
        if 'LastEvaluatedKey' not in response:
            break
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']

    return list(user_ids)


def lambda_handler(event, context):
    """
    Entry point triggered by EventBridge on a daily schedule.

    Flow:
      1. Compute yesterday/today as the sync window (full previous calendar day).
      2. Scan Main table to get all registered user IDs.
      3. For each user, async-invoke transaction-analytics-lambda with userId + date range.
         InvocationType='Event' means fire-and-forget — this dispatcher does NOT wait
         for each sync to complete. Each user's sync runs fully independently.
      4. Return a summary of dispatched vs failed invocations.

    The EventBridge event payload itself is intentionally ignored — all the
    information this lambda needs (users, dates) comes from DynamoDB + system time.
    """
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    print(f"Daily sync starting. Window: {yesterday} → {today}")

    user_ids = get_all_user_ids()
    print(f"Found {len(user_ids)} user(s). Dispatching async syncs...")

    dispatched: list[str] = []
    failed: list[str] = []

    for user_id in user_ids:
        payload = {
            'userId': user_id,
            'start_date': str(yesterday),
            'end_date': str(today)
        }

        try:
            # InvocationType='Event' → async invocation.
            # This dispatcher returns immediately after firing; transaction-analytics-lambda
            # runs in the background. AWS will retry the downstream lambda up to 2 times
            # on failure via its own async invocation retry policy.
            lambda_client.invoke(
                FunctionName=TXN_ANALYTICS_LAMBDA_NAME,
                InvocationType='Event',
                Payload=json.dumps(payload)
            )
            print(f"  ✓ Dispatched sync for user: {user_id}")
            dispatched.append(user_id)

        except Exception as e:
            # A failed invocation here means the Lambda service couldn't accept the request
            # (e.g. throttle, permissions issue). Log and continue so one bad user
            # doesn't block the rest of the batch.
            print(f"  ✗ Failed to dispatch for user {user_id}: {e}")
            failed.append(user_id)

    summary = {
        'date_window': {'start': str(yesterday), 'end': str(today)},
        'total_users': len(user_ids),
        'dispatched': len(dispatched),
        'failed': len(failed),
        'failed_users': failed
    }

    print(f"Dispatch complete. Summary: {json.dumps(summary)}")

    return {
        'statusCode': 200,
        'body': summary
    }
