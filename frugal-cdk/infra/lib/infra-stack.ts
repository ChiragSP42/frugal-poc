import * as cdk from 'aws-cdk-lib/core';
import * as aws_lambda from 'aws-cdk-lib/aws-lambda';
import * as aws_logs from 'aws-cdk-lib/aws-logs';
import * as aws_iam from 'aws-cdk-lib/aws-iam';
import * as aws_dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as aws_events from 'aws-cdk-lib/aws-events';
import * as aws_events_targets from 'aws-cdk-lib/aws-events-targets';
import * as path from 'path';
import * as dotenv from 'dotenv';
import * as aws_ecr_assests from 'aws-cdk-lib/aws-ecr-assets';
import { Construct } from 'constructs';

dotenv.config({
  path: path.join(__dirname, "../../../.env")
})

export class InfraStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    //============================
    //*******LAMBDAS**************
    //============================

    // Card recommendation engine lambda-----------
    const card_rec_lambda_name = 'card-recommendation-lambda'

    const card_rec_log = new aws_logs.LogGroup(this, 'CardRecommendationLogGroup', {
      logGroupName: `/aws/lambda/${card_rec_lambda_name}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: aws_logs.RetentionDays.ONE_MONTH
    })

    const card_rec_lambda = new aws_lambda.DockerImageFunction(this, 'CardRecommendationEngine', {
      functionName: card_rec_lambda_name,
      description: 'Card recommendation engine that will map card category to ALS category and Plaid transaction category to card category',
      logGroup: card_rec_log,
      code: aws_lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, '../../services/lambdas/card-recommendation-lambda'),
        { platform: aws_ecr_assests.Platform.LINUX_AMD64 }
      ),
      timeout: cdk.Duration.minutes(5),
      memorySize: 2048,
      ephemeralStorageSize: cdk.Size.gibibytes(8),
      environment: {
        USER_CARDS_TABLE_NAME: process.env.USER_CARDS_TABLE_NAME || "Frugal-UserCards-dev",
        TXN_TABLE_NAME: process.env.TXN_TABLE_NAME || "Frugal-Txn-dev",
        REFERENCE_TABLE_NAME: process.env.REFERENCE_TABLE_NAME || "Frugal-Reference-dev"
      }
    })

    const user_cards_table = aws_dynamodb.TableV2.fromTableName(this, 'UserCardsTable', process.env.USER_CARDS_TABLE_NAME || 'Frugal-UserCards-dev')
    const txn_table = aws_dynamodb.TableV2.fromTableName(this, 'TransactionsTable', process.env.TXN_TABLE_NAME || 'Frugal-Txn-dev')
    const ref_table = aws_dynamodb.TableV2.fromTableName(this, 'ReferenceTable', process.env.REFERENCE_TABLE_NAME || 'Frugal-Reference-dev')

    user_cards_table.grantReadData(card_rec_lambda)
    txn_table.grantReadData(card_rec_lambda)
    ref_table.grantReadData(card_rec_lambda)
    card_rec_lambda.addToRolePolicy(new aws_iam.PolicyStatement({
      actions: [
        'kms:Decrypt',
        'kms:Encrypt',
        'kms:GenerateDataKey*'
      ],
      resources: ['*'],
      conditions: {
        StringEquals: {
          'kms:ViaService': `dynamodb.${this.region}.amazonaws.com`,
          'kms:CallerAccount': this.account
        }
      }
    }));
    card_rec_lambda.addToRolePolicy(new aws_iam.PolicyStatement({
      actions: [
        'dynamodb:BatchWriteItem'
      ],
      resources: [`arn:aws:dynamodb:${this.region}:${this.account}:table/${txn_table.tableName}`]
    }));

    // Transaction analytics lambda----------------

    const txn_analytics_lambda_name = 'transaction-analytics-lambda'

    const txn_analytics_log_group = new aws_logs.LogGroup(this, 'TransactionAnalyticsLogGroup', {
      logGroupName: `/aws/lambda/${txn_analytics_lambda_name}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: aws_logs.RetentionDays.ONE_MONTH
    })

    const transaction_analytics_lambda = new aws_lambda.DockerImageFunction(this, 'TransactionAnalytics', {
      functionName: txn_analytics_lambda_name,
      description: 'Given a start and end date, it will retrieve transactions from Plaid, process them using the card recommendation engine and store in DDB',
      logGroup: txn_analytics_log_group,
      code: aws_lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, '../../services/lambdas/transaction-analytics-lambda'),
        { platform: aws_ecr_assests.Platform.LINUX_AMD64 }
      ),
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
      ephemeralStorageSize: cdk.Size.gibibytes(2),
      environment: {
        RECOMMENDATION_ENGINE_LAMBDA_NAME: card_rec_lambda_name,
        USER_CARDS_TABLE_NAME: process.env.USER_CARDS_TABLE_NAME || "",
        PLAID_CLIENT_ID: process.env.PLAID_CLIENT_ID || "",
        PLAID_SECRET: process.env.PLAID_SECRET || "",
        MAIN_TABLE_NAME: process.env.MAIN_TABLE_NAME || ""
      }
    })

    const main_table = aws_dynamodb.TableV2.fromTableName(this, 'MainTable', process.env.MAIN_TABLE_NAME || 'Frugal-Main-dev')

    card_rec_lambda.grantInvoke(transaction_analytics_lambda)
    user_cards_table.grantReadData(transaction_analytics_lambda)
    main_table.grantReadData(transaction_analytics_lambda)
    transaction_analytics_lambda.addToRolePolicy(new aws_iam.PolicyStatement({
      actions: [
        'kms:Decrypt',
        'kms:Encrypt',
        'kms:GenerateDataKey*'
      ],
      resources: ['*'],
      conditions: {
        StringEquals: {
          'kms:ViaService': `dynamodb.${this.region}.amazonaws.com`,
          'kms:CallerAccount': this.account
        }
      }
    }));

    //============================
    //**** DAILY PLAID SYNC ******
    //============================

    // Daily Plaid sync dispatcher lambda----------
    const daily_sync_lambda_name = 'daily-plaid-sync-lambda'

    const daily_sync_log = new aws_logs.LogGroup(this, 'DailyPlaidSyncLogGroup', {
      logGroupName: `/aws/lambda/${daily_sync_lambda_name}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: aws_logs.RetentionDays.ONE_MONTH
    })

    const daily_sync_lambda = new aws_lambda.DockerImageFunction(this, 'DailyPlaidSync', {
      functionName: daily_sync_lambda_name,
      description: 'Scans DynamoDB Main table for all users and fans out a daily Plaid sync by async-invoking transaction-analytics-lambda per user',
      logGroup: daily_sync_log,
      code: aws_lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, '../../services/lambdas/daily-plaid-sync-lambda'),
        { platform: aws_ecr_assests.Platform.LINUX_AMD64 }
      ),
      // Timeout must exceed the total time to loop through all users and fire async invocations.
      // 5 minutes is safe for a POC (5-10 users). Revisit at MVP scale.
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: {
        MAIN_TABLE_NAME: process.env.MAIN_TABLE_NAME || 'Frugal-Main-dev',
        TXN_ANALYTICS_LAMBDA_NAME: txn_analytics_lambda_name
      }
    })

    // Allow the sync dispatcher to read user records from the Main table
    // (reuses the main_table reference already defined above)
    main_table.grantReadData(daily_sync_lambda)

    // Allow the sync dispatcher to async-invoke the transaction analytics lambda
    transaction_analytics_lambda.grantInvoke(daily_sync_lambda)

    // KMS — needed to read KMS-encrypted items from DynamoDB (same scoped policy as other lambdas)
    daily_sync_lambda.addToRolePolicy(new aws_iam.PolicyStatement({
      actions: [
        'kms:Decrypt',
        'kms:GenerateDataKey*'
      ],
      resources: ['*'],
      conditions: {
        StringEquals: {
          'kms:ViaService': `dynamodb.${this.region}.amazonaws.com`,
          'kms:CallerAccount': this.account
        }
      }
    }))

    // EventBridge Rule — fires daily at 02:00 UTC
    // Runs after midnight so "yesterday" maps cleanly to the previous full calendar day
    const daily_sync_rule = new aws_events.Rule(this, 'DailyPlaidSyncSchedule', {
      ruleName: 'daily-plaid-sync-schedule',
      description: 'Triggers daily-plaid-sync-lambda at 02:00 UTC every day',
      schedule: aws_events.Schedule.cron({
        minute: '0',
        hour: '2',
        day: '*',
        month: '*',
        year: '*'
      })
    })

    // Wire the EventBridge rule to the dispatcher lambda.
    // retryAttempts: 2 means EventBridge will retry the dispatcher itself up to 2 times
    // if it fails to invoke (e.g. throttle). Each user's downstream sync has its own retry
    // logic inside the lambda.
    daily_sync_rule.addTarget(new aws_events_targets.LambdaFunction(daily_sync_lambda, {
      retryAttempts: 2
    }))
  }
}