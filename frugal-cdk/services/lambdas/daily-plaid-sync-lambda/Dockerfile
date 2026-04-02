FROM public.ecr.aws/lambda/python:3.13

COPY requirements.txt ${LAMBDA_TASK_ROOT}

RUN pip install --no-cache-dir -r requirements.txt

COPY daily_plaid_sync.py ${LAMBDA_TASK_ROOT}

CMD ["daily_plaid_sync.lambda_handler"]