import boto3
import json
import numpy as np
import os

# Environment variables
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY')
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")

POC_EMBEDDINGS = {
    "Dining": np.array([0.012, -0.045, 0.112]),       
    "Groceries": np.array([0.104, 0.021, -0.055]),
    "Retail": np.array([0.332, 0.111, 0.001]),
    "Travel": np.array([-0.551, 0.882, 0.102]),
    "Digital Entertainment": np.array([0.002, -0.004, 0.505])
}

session = boto3.Session(aws_access_key_id=AWS_ACCESS_KEY,
                        aws_secret_access_key=AWS_SECRET_KEY,
                        region_name='us-east-1')

bedrock_client = session.client("bedrock-runtime")

# UNKNOWN category
body = json.dumps({"inputText": 'Netflix'})
response = bedrock_client.invoke_model(
    body=body,
    modelId='amazon.titan-embed-text-v1',
    accept='application/json',
    contentType='application/json'
)
response_body = json.loads(response.get('body').read())

# Convert the returned list into a numpy array
unknown_vector = np.array(response_body.get('embedding'))

best_match = "Retail"
highest_score = 0.0

print(f"Before: Best match: {best_match}\nHighest score: {highest_score}")

# KNOWN category
for poc_category in POC_EMBEDDINGS.keys():
    body = json.dumps({"inputText": poc_category})
    response = bedrock_client.invoke_model(
        body=body,
        modelId='amazon.titan-embed-text-v1',
        accept='application/json',
        contentType='application/json'
    )
    response_body = json.loads(response.get('body').read())

    # Convert the returned list into a numpy array
    poc_vector = np.array(response_body.get('embedding'))

    # Cosine similarity calculation
    score = np.dot(unknown_vector, poc_vector) / (np.linalg.norm(unknown_vector) * np.linalg.norm(poc_vector))

    print(f"\nCategory: {poc_category} -> Score: {score}")
            
    if score > highest_score:
        highest_score = score
        best_match = poc_category

print(f"\nAfter: Best match: {best_match}\nHighest score: {highest_score}")

        