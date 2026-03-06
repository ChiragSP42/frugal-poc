# Requires transformers>=4.51.0
# Requires sentence-transformers>=2.7.0

from sentence_transformers import SentenceTransformer

# Load the model
# model = SentenceTransformer("Qwen/Qwen3-Embedding-4B")
model = SentenceTransformer("jinaai/jina-embeddings-v5-text-nano", 
                            trust_remote_code=True,
                            model_kwargs={'default_task': 'retrieval', 
                                          "attn_implementation": "flash_attention_2", 
                                          "device_map": "auto"},
                            tokenizer_kwargs={"padding_side": "left"})

# We recommend enabling flash_attention_2 for better acceleration and memory saving,
# together with setting `padding_side` to "left":
# model = SentenceTransformer(
#     "Qwen/Qwen3-Embedding-4B",
#     model_kwargs={"attn_implementation": "flash_attention_2", "device_map": "auto"},
#     tokenizer_kwargs={"padding_side": "left"},
# )

# The queries and documents to embed
queries = [
    "Netflix",
]
documents = [
    "Dining",
    "Groceries",
    "Travel",
    "Retail",
    "Digital Entertainment",
    "FOOD_AND_DRINK",
    "ENTERTAINMENT",
    "GENERAL_MERCHANDISE",
    "TRAVEL",
]

# Encode the queries and documents. Note that queries benefit from using a prompt
# Here we use the prompt called "query" stored under `model.prompts`, but you can
# also pass your own prompt via the `prompt` argument
query_embeddings = model.encode(queries)
document_embeddings = model.encode(documents)

# Compute the (cosine) similarity between the query and document embeddings
similarity = model.similarity(query_embeddings, document_embeddings)
print(similarity)
# tensor([[0.7534, 0.1147],
#         [0.0320, 0.6258]])
