from sentence_transformers import SentenceTransformer
import numpy as np

# Load the model
model = SentenceTransformer("jinaai/jina-embeddings-v5-text-nano", 
                            trust_remote_code=True,
                            model_kwargs={'default_task': 'retrieval', 
                                          "attn_implementation": "flash_attention_2", 
                                          "device_map": "auto"},
                            tokenizer_kwargs={"padding_side": "left"})

# The queries and documents to embed
# queries = [
#     "Netflix",
# ]
# documents = [
#     "Dining",
#     "Groceries",
#     "Travel",
#     "Retail",
#     "Digital Entertainment",
#     "FOOD_AND_DRINK",
#     "ENTERTAINMENT",
#     "GENERAL_MERCHANDISE",
#     "TRAVEL",
# ]

unknown_category = ['Fast Food']

card_categories = np.array([["Supermarkets", "Supermarkets", "Grocery stores, dining and entertainment", "Dining and drugstores"],
                            ["Online Retail","U.S. Streaming", None, "Travel"],
                            ["Gas stations", "Transit", None, None]], dtype=str)

unknown_category_embeddings = model.encode(unknown_category)
card_category_embeddings = model.encode(card_categories)

# Compute the (cosine) similarity between the query and document embeddings
similarity = model.similarity(unknown_category_embeddings, card_category_embeddings)
print(similarity)
