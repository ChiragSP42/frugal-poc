import os
import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv
load_dotenv(override=True)

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
USER_CARDS_TABLE_NAME = os.getenv("USER_CARDS_TABLE_NAME")

session = boto3.Session(aws_access_key_id=AWS_ACCESS_KEY,
                        aws_secret_access_key=AWS_SECRET_KEY,
                        region_name='us-east-1')

dynamodb = session.resource('dynamodb')
table = dynamodb.Table(USER_CARDS_TABLE_NAME) #type: ignore

response = table.query(KeyConditionExpression=Key('userId').eq('Chirag'))

print(response)