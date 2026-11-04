"""Check whether the configured Pinecone account can supply boundary embeddings."""

import os

from pinecone import Pinecone

from financial_rag.config import load_env

if __name__ == "__main__":
    load_env()
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    response = pc.inference.list_models(type="embed")
    print(response.to_dict())
