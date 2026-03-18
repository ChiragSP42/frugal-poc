import * as cdk from 'aws-cdk-lib/core';
import * as aws_lambda from 'aws-cdk-lib/aws-lambda';
import * as aws_logs from 'aws-cdk-lib/aws-logs';
import * as aws_iam from 'aws-cdk-lib/aws-iam';
import * as aws_dynamodb from 'aws-cdk-lib/aws-dynamodb';
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
        {
          platform: aws_ecr_assests.Platform.LINUX_AMD64
        }
      ),
      timeout: cdk.Duration.minutes(5),
      memorySize: 3072,
      ephemeralStorageSize: cdk.Size.gibibytes(8),
      environment: {
        USER_CARDS_TABLE_NAME: process.env.USER_CARDS_TABLE_NAME || ""
      }
    })

    const table = aws_dynamodb.TableV2.fromTableName(this, 'MeetingsTable', process.env.USER_CARDS_TABLE_NAMETABLE_NAME || 'Frugal-UserCards-dev')

    table.grantReadData(card_rec_lambda)
    card_rec_lambda.addToRolePolicy(new aws_iam.PolicyStatement({
      actions: [
        'kms:Decrypt',
        'kms:Encrypt',
        'kms:GenerateDataKey*'
      ],
      resources: ['*'], // Allow any key...
      conditions: {
        StringEquals: {
          // ...BUT only if DynamoDB is the service asking for it
          'kms:ViaService': `dynamodb.${this.region}.amazonaws.com`,
          'kms:CallerAccount': this.account
        }
      }
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
        {
          platform: aws_ecr_assests.Platform.LINUX_AMD64
        }
      ),
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
      ephemeralStorageSize: cdk.Size.gibibytes(2)
    })
  }
}
