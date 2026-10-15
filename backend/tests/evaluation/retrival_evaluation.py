import json
import numpy as np
import asyncio
import sys
from uuid import UUID

BACKEND_PATH = "/home/user/Documents/Project_5/backend"
if BACKEND_PATH not in sys.path:
    sys.path.append(BACKEND_PATH)

from app.rag.retrival.retrival import Retrival
from app.rag.embedder.embedder import Embedder
from app.core.config import env_config

from fastembed.rerank.cross_encoder import TextCrossEncoder

# print(TextCrossEncoder.list_supported_models())
encoder = "Xenova/ms-marco-MiniLM-L-6-v2"
reranker = TextCrossEncoder(model_name=encoder)

retriver = Retrival()
embedder = Embedder(model_name="BAAI/bge-small-en-v1.5")

REPO_ID = UUID(env_config.REPO_ID or "")


async def rerank(query: str, docs: list[dict], top_k):
    chunks = [item["chunk_str"] for item in docs]
    scores = list(reranker.rerank(query, chunks))

    ranked_items = sorted(zip(scores, docs), key=lambda pair: pair[0], reverse=True)
    results = [{**item, "rerank_score": score} for score, item in ranked_items]
    return results[:top_k]


async def retrival(query: str, top_k: int):
    rrf_array = []
    # embedded_query = await asyncio.to_thread(lambda: embedder.embed(query))
    # searcher = list(embedded_query)[0].tolist()
    # vec = await retriver._retrive_by_vector_distance(
    #     embeded_query=searcher, repo_id=REPO_ID
    # )
    # trg = await retriver._retrive_by_trigram_similarity(query=query, repo_id=REPO_ID)
    # rrf_array.append(vec)
    # rrf_array.append(trg)
    # retrived_doc = await retriver._retrive_by_fts(
    #     query=query, repo_id=REPO_ID
    # )
    # retrived_doc = await retriver._retrive_by_fts(query=query, repo_id=REPO_ID)
    # retrived_doc = await retriver.retrive(query, embedded_query, REPO_ID, top_chunk=top_k)
    type = "error"
    content = ""
    count = 0
    while type != "success" and content == "" and count < 4:
        count += 1
        rewriten_query = await retriver._rewrite_query(query)
        content = rewriten_query.get("content", None)
        if content:
            print(content)
            embedded_query = await asyncio.to_thread(lambda: embedder.embed(content))
            searcher = list(embedded_query)[0].tolist()
            vec_ai = await retriver._retrive_by_vector_distance(
                embeded_query=searcher, repo_id=REPO_ID
            )
            trg_ai = await retriver._retrive_by_trigram_similarity(
              query=content, repo_id=REPO_ID
             )

            rrf_array.append(vec_ai)
            rrf_array.append(trg_ai)
    # rewriten_query = await retriver._rewrite_query(query, "groq/openai/gpt-oss-120b")
    # content = rewriten_query.get("content", None)
    # if content:
    #     print(content)
    #     embedded_query = await asyncio.to_thread(lambda: embedder.embed(content))
    #     searcher = list(embedded_query)[0].tolist()
    #     vec_ai = await retriver._retrive_by_vector_distance(
    #         embeded_query=searcher, repo_id=REPO_ID
    #     )
    #     trg_ai = await retriver._retrive_by_trigram_similarity(
    #         query=content, repo_id=REPO_ID
    #     )

    #     rrf_array.append(vec_ai)
    #     rrf_array.append(trg_ai)
    if not rrf_array:
        print("No results found for the query.")
        # return {"docs": [], "ai_query": content}
        raise ValueError(
            f"No results found for the query. query: {query}, rewriten_query: {content}"
        )
    retrived_doc = retriver._merge_results_rrf_multi(rrf_array)
    return {"docs": retrived_doc[:top_k], "ai_query": content}


async def run_local_rag_evaluation(
    json_path, top_k=10, output_path="evaluation_results.json"
):
    # 1. Load the golden dataset
    print(f"Loading dataset from {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    per_query_results = []

    hit_rates = []
    precisions = []
    recalls = []
    mrrs = []
    maps = []

    # print(f"Evaluating {len(dataset)} queries (Top-K={top_k})...")

    # 2. Iterate through each query in the dataset
    for item in dataset:
        query = item["query"]
        true_ids = set(item["relevant_embed_ids"])
        ground_truth_answer = item.get("ground_truth_answer", "")

        # Query your local vector store (adjust based on your actual vector store API)
        # Assuming similarity_search returns documents where metadata contains the "id"
        retrieved_docs = await retrival(query, top_k)
        docs = retrieved_docs["docs"]
        ai_query = retrieved_docs.get("ai_query")
        # rd = await rerank(ai_query if ai_query else query, docs, top_k)
        retrieved_ids = [str(doc["embed_id"]) for doc in docs]

        # Compute hits for strict ID matching
        hits = [1 if r_id in true_ids else 0 for r_id in retrieved_ids]

        # Metric Calculations
        # 1. Hit Rate@K: 1 if at least one retrieved chunk is relevant, else 0
        hit_rate = 1 if sum(hits) > 0 else 0

        # 2. Precision@K: Fraction of retrieved chunks that are relevant
        num_relevant_retrieved = sum(hits)
        precision = num_relevant_retrieved / top_k if top_k > 0 else 0.0

        # 3. Recall@K: Fraction of true relevant chunks successfully retrieved
        recall = num_relevant_retrieved / len(true_ids) if len(true_ids) > 0 else 0.0

        # 4. MRR (Mean Reciprocal Rank): Position of the first correct hit
        rr = 0.0
        for rank, hit in enumerate(hits, start=1):
            if hit == 1:
                rr = 1.0 / rank
                break

        # 5. MAP Component (Average Precision for this query)
        ap_score = 0.0
        num_hits_accumulated = 0.0
        for i, hit in enumerate(hits):
            if hit == 1:
                num_hits_accumulated += 1.0
                ap_score += num_hits_accumulated / (i + 1.0)
        ap = ap_score / len(true_ids) if len(true_ids) > 0 else 0.0

        # Collect for aggregate tracking
        hit_rates.append(hit_rate)
        precisions.append(precision)
        recalls.append(recall)
        mrrs.append(rr)
        maps.append(ap)

        # Store structured data for this specific query
        per_query_results.append(
            {
                "query": query,
                "ground_truth_answer": ground_truth_answer,
                "true_relevant_ids": list(true_ids),
                "retrieved_ids": retrieved_ids,
                "metrics": {
                    "hit_rate": hit_rate,
                    "precision": round(precision, 4),
                    "recall": round(recall, 4),
                    "mrr": round(rr, 4),
                    "map": round(ap, 4),
                },
            }
        )

    # 3. Calculate summary averages
    summary = {
        "used_tech": ["vector", "trigram", "query rewriting", ],
        "model_name": "BAAI/bge-small-en-v1.5",
        "rewriting_model": "groq/qwen/qwen3.8-27b",
        "total_queries": len(dataset),
        "top_k": top_k,
        "mean_hit_rate": round(float(np.mean(hit_rates)), 4),
        "mean_precision": round(float(np.mean(precisions)), 4),
        "mean_recall": round(float(np.mean(recalls)), 4),
        "mean_mrr": round(float(np.mean(mrrs)), 4),
        "mean_map": round(float(np.mean(maps)), 4),
    }

    final_output = {"summary": summary, "per_query_results": per_query_results}

    # 4. Save results back to JSON file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4)

    print(f"\nEvaluation complete! Results successfully saved to {output_path}")
    print("--- Summary Results ---")
    for k, v in summary.items():
        print(f"{k}: {v}")

    return final_output


FILE_PATH = (
    "/home/user/Documents/Project_5/backend/tests/evaluation/golden_dataset_syn.json"
)
OUTPUT_PATH = "/home/user/Documents/Project_5/backend/tests/evaluation/reports/retrieval_eval_vec_trg_rewrite_final.json"

asyncio.run(
    run_local_rag_evaluation(
        json_path=FILE_PATH,
        top_k=8,
        output_path=OUTPUT_PATH,
    )
)
