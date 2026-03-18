FROM public.ecr.aws/lambda/python:3.13

COPY requirements.txt ${LAMBDA_TASK_ROOT}

RUN pip install --no-cache-dir -r requirements.txt

COPY card_recommendation_lambda.py ${LAMBDA_TASK_ROOT}

# Set the cache directory to somewhere inside the container task folder
ENV HF_HOME="/var/task/hf_cache"

# Pre-download the model during the build phase
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('jinaai/jina-embeddings-v5-text-nano', trust_remote_code=True)"

# So that Transformers only looks for local files to load model
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
# Silence joblib shared memory warning
ENV JOBLIB_MULTIPROCESSING=0

CMD ["card_recommendation_lambda.lambda_handler"]