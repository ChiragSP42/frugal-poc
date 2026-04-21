FROM public.ecr.aws/lambda/python:3.13

COPY requirements.txt ${LAMBDA_TASK_ROOT}

RUN pip install --no-cache-dir -r requirements.txt

COPY spending_cat_lambda.py ${LAMBDA_TASK_ROOT}

CMD ["spending_cat_lambda.lambda_handler"]