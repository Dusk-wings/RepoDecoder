import argparse
import sys
from uuid import UUID
import logging
import asyncio
import json
from pathlib import Path
import time
from collections import Counter

BACKEND_PATH = "/home/user/Documents/Project_5/backend"
if BACKEND_PATH not in sys.path:
    sys.path.append(BACKEND_PATH)


from app.rag.retrival.retrival import Retrival
from app.rag.embedder.embedder import Embedder
from app.rag.generator.generator import Generator
from app.core.supabase import get_supabase_async_client
from app.core.config import env_config

from app.core.config import env_config

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ID = UUID(env_config.REPO_ID or "")
INPUT_FILE_PATH = (
    "/home/user/Documents/Project_5/backend/tests/evaluation/golden_dataset_syn.json"
)
OUTPUT_FILE_PATH = "/home/user/Documents/Project_5/backend/tests/evaluation/reports/generation_evaluation_report_resample.json"

GENERATION_MODEL = "google/gemini-3.5-flash-lite"
QWERY_REWRITE_MODEL = "groq/openai/gpt-oss-120b"
EVALUATION_MODEL = "google/gemini-3.5-flash-lite"
TOP_CHUNK = 20


class GenerationError(RuntimeError):
    def __init__(self, message: str, status_code: int | None):
        super().__init__(message)
        self.status_code = status_code


EVALUATOR_PROMPT = """
You are an evaluator for a code-focused RAG system.

Evaluate the generated answer using the supplied inputs.

USER QUESTION:
{question}

GROUND-TRUTH ANSWER:
{ground_truth_answer}

RETRIEVED CODE CHUNKS:
{retrieved_chunks}

GENERATED ANSWER:
{generated_answer}

Evaluate the generated answer on each dimension independently, using a score from 0 to 2. Do not let a score on one dimension determine the others.

1. Correctness (0-2)  
   Compare the generated answer with the ground-truth answer. Accept semantically equivalent explanations; identical wording is not required. Do not reward contradictions or invented details.  
   - 2: Correct; no material errors.  
   - 1: Partially correct, but incomplete or contains a minor error.  
   - 0: Incorrect or contradicted on a central point.

2. Faithfulness to retrieved context (0-2)  
   Check whether the answer's factual and implementation-specific claims are supported by the retrieved code chunks. The ground-truth answer is not evidence that a claim is supported by those chunks.  
   - 2: All material claims are supported by the retrieved chunks.  
   - 1: Some claims are supported, but others are unsupported, overstated, or unclear from the chunks.  
   - 0: The answer's central claims are unsupported or contradicted by the chunks.

3. Completeness (0-2)  
   Using the ground-truth answer as a reference, determine whether the generated answer covers the essential information needed to answer the question. Do not penalize harmless wording differences or unnecessary implementation details that do not affect correctness.  
   - 2: Covers all essential information.  
   - 1: Covers some essential information but omits a significant point.  
   - 0: Omits most or all of the essential information.

4. Answerability from retrieved context (0-2)  
   Determine whether the question can be answered from the retrieved context, regardless of whether the generated answer answered it correctly.  
   - 2: The context contains enough information to answer the question.  
   - 1: The context supports only a partial answer or leaves important ambiguity.  
   - 0: The context does not contain enough information to answer the question.

Score each dimension separately and briefly justify each score.

For each dimension, return:
- score: integer from 0 to 2
- reason: brief explanation based on the supplied evidence

If the reference or evidence is insufficient to judge a dimension,
say so in its reason rather than guessing.

OUTPUT REQUIREMENTS:
- Return exactly one valid JSON object matching the structure below.
- Do not include Markdown, code fences, a ```json label, commentary, explanations, or any text before or after the JSON.
- Use double quotes for all keys and string values. Scores must be integers from 0 to 2.
- Do not add, remove, or rename keys.

{{
  "correctness": {{"score": 0, "reason": "..."}},
  "faithfulness": {{"score": 0, "reason": "..."}},
  "completeness": {{"score": 0, "reason": "..."}},
  "answerability": {{"score": 0, "reason": "..."}}
}}
"""
def clean_text(value: str) -> str:
    return value.replace("\x00", "")

async def retrive_relevant_chunks(
    query: str, embedder: Embedder, retriver: Retrival, top_chunk: int = TOP_CHUNK
):
    retry_count = 0
    ai_res_type = "error"
    content = None

    logger.info("[EVAL-RETRIVAL] RETRIVING FOR QUERY, %s\n", query)
    while retry_count < 3 and ai_res_type != "success":
        retry_count += 1
        try:
            ai_query = await retriver._rewrite_query(
                query=query,
                history=[],
                model=QWERY_REWRITE_MODEL,
                api_key=env_config.EVALUATION_API_KEY,
            )
            ai_res_type = ai_query["type"]
            content = ai_query.get("content", None)

            if content is not None:
                embeded_query = embedder.embed(content)
                for retrying in range(4):
                    try:
                        content = clean_text(content)
                        retrived_chunks = await retriver.retrive(
                            content, embeded_query, repo_id=REPO_ID, top_chunk=top_chunk
                        )
                        return retrived_chunks
                    except Exception as e:
                        logger.exception(
                            "[EVAL-RETRIVAL] ERROR WHILE RETRIVING CHUNKS, %s", e
                        )

        except Exception as e:
            logger.exception("[EVAL-RETRIVAL] ERROR WHILE GENERATEING THE ERROR, %s", e)


async def generate_the_content(
    query: str, retrived_content: list, generator: Generator
):
    stop_event = asyncio.Event()
    bucket_cleint = await get_supabase_async_client()

    generated_content = []

    messages = generator.generate_chat_content(
        user_message=query, retrived_content=retrived_content
    )
    logger.info("[EVAL-GENERATOR] GENRATING THE ANSWER OF THE QUERY")
    async for data in generator.LLM_generator(
        model=GENERATION_MODEL,
        stop_event=stop_event,
        bucket_client=bucket_cleint,
        repo_id=REPO_ID,
        messages=messages,
        max_tokens=1000,
    ):
        data_type = data["type"]
        if data_type == "token":
            generated_content.append(data.get("content"))
        #     print(data)
        # elif data_type == "tool_call":
        #     print(data)

        elif data_type == "error":
            raise GenerationError(
                message=data.get("content", "Generation failed."),
                status_code=data.get("status_code"),
            )
        if data_type == "end":
            break

    logger.info("[EVAL-GENERATOR] GENERATION COMPLETE")
    return "".join(generated_content)


def load_dataset(path: str):
    logger.info("[EVAL-LOADER] LOADING DATASET")
    with open(path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    logger.info("[EVAL-LOADER] DATASET LOADED")
    return [
        {"query": data["query"], "ground_truth": data["ground_truth_answer"]}
        for data in dataset
    ]


async def save_dataset(data: dict, path: str):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(data, output_file, indent=2, ensure_ascii=False)
    temporary_path.replace(output_path)


def load_existing_results(path: str) -> list[dict]:
    output_path = Path(path)
    if not output_path.exists():
        return []

    with output_path.open("r", encoding="utf-8") as input_file:
        report = json.load(input_file)

    results = report.get("per_query_results") if isinstance(report, dict) else None
    if not isinstance(results, list):
        raise ValueError(f"Existing evaluation report has an invalid format: {path}")
    return results


def build_report(per_query_results: list[dict], evaluation_model: str) -> dict:
    dimensions = ("correctness", "faithfulness", "completeness", "answerability")
    scored_results = [
        result
        for result in per_query_results
        if all(
            isinstance(result.get("scores", {}).get(dimension), int)
            and not isinstance(result["scores"][dimension], bool)
            for dimension in dimensions
        )
    ]
    average_scores = {
        dimension: (
            round(
                sum(result["scores"][dimension] for result in scored_results)
                / len(scored_results),
                4,
            )
            if scored_results
            else None
        )
        for dimension in dimensions
    }
    return {
        "summary": {
            "total_queries": len(per_query_results),
            "scored_queries": len(scored_results),
            "average_scores": average_scores,
            "evaluation_model": evaluation_model,
        },
        "per_query_results": per_query_results,
    }


def recalculate_average_scores(
    input_file_path: str, output_file_path: str = OUTPUT_FILE_PATH
) -> dict:
    with open(input_file_path, "r", encoding="utf-8") as input_file:
        dataset = json.load(input_file)
    if not isinstance(dataset, list):
        raise ValueError(f"Evaluation dataset must contain a list: {input_file_path}")

    output_path = Path(output_file_path)
    with output_path.open("r", encoding="utf-8") as output_file:
        report = json.load(output_file)
    if not isinstance(report, dict) or not isinstance(
        report.get("per_query_results"), list
    ):
        raise ValueError(
            f"Existing evaluation report has an invalid format: {output_path}"
        )

    results = report["per_query_results"]
    selected_results = []
    selected_indices = set()
    for result in results:
        dataset_index = result.get("dataset_index")
        if dataset_index is None and isinstance(result.get("query"), str):
            selected_results.append(result)
            continue
        if (
            isinstance(dataset_index, int)
            and not isinstance(dataset_index, bool)
            and 0 <= dataset_index
            and result.get("query")
        ):
            selected_results.append(result)
            selected_indices.add(dataset_index)

    remaining_queries = Counter(
        item.get("query")
        for index, item in enumerate(dataset)
        if index not in selected_indices and isinstance(item.get("query"), str)
    )
    for result in results:
        if "dataset_index" not in result:
            query = result.get("query")
            if isinstance(query, str) and remaining_queries[query] > 0:
                selected_results.append(result)
                remaining_queries[query] -= 1

    evaluation_model = report.get("summary", {}).get("evaluation_model", "")
    recalculated = build_report(selected_results, evaluation_model)["summary"]
    recalculated["total_queries"] = len(results)
    report["summary"] = recalculated

    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(report, output_file, indent=2, ensure_ascii=False)
    temporary_path.replace(output_path)
    return recalculated


def replace_query_result(per_query_results: list[dict], new_result: dict) -> list[dict]:
    query = new_result["query"]
    normalized_query = " ".join(query.split())
    for index, result in enumerate(per_query_results):
        existing_query = result.get("query")
        if (
            isinstance(existing_query, str)
            and " ".join(existing_query.split()) == normalized_query
        ):
            replacement = new_result.copy()
            if replacement.get("dataset_index") is None and "dataset_index" in result:
                replacement["dataset_index"] = result["dataset_index"]
            return (
                per_query_results[:index]
                + [replacement]
                + per_query_results[index + 1 :]
            )

    return per_query_results + [new_result]


async def main():
    parser = argparse.ArgumentParser(description="Run generation evaluation.")
    parser.add_argument(
        "--query",
        help="Evaluate one custom query instead of processing the golden dataset.",
    )
    parser.add_argument(
        "--ground-truth",
        help="Optional reference answer for a custom query.",
    )
    args = parser.parse_args()

    if args.ground_truth and not args.query:
        parser.error("--ground-truth can only be used with --query")

    retrival = Retrival()
    embedder = Embedder()
    generator = Generator()

    is_custom_query = args.query is not None
    if is_custom_query:
        dataset = [
            {
                "query": args.query,
                "ground_truth": args.ground_truth
                or "No ground-truth answer was provided for this query.",
            }
        ]
    else:
        dataset = load_dataset(INPUT_FILE_PATH)
    per_query_results = load_existing_results(OUTPUT_FILE_PATH)
    evaluation_model = EVALUATION_MODEL
    completed_indices = {
        result["dataset_index"]
        for result in per_query_results
        if isinstance(result.get("dataset_index"), int)
    }
    legacy_completed_queries = Counter(
        result["query"]
        for result in per_query_results
        if "dataset_index" not in result and isinstance(result.get("query"), str)
    )

    await save_dataset(
        build_report(per_query_results, evaluation_model), OUTPUT_FILE_PATH
    )

    for dataset_index, data in enumerate(dataset):
        query = data["query"]
        if not is_custom_query and dataset_index in completed_indices:
            logger.info("[EVAL-RESUME] SKIPPING COMPLETED QUERY %s", query)
            continue
        if not is_custom_query and legacy_completed_queries[query] > 0:
            legacy_completed_queries[query] -= 1
            logger.info("[EVAL-RESUME] SKIPPING PREVIOUSLY SAVED QUERY %s", query)
            continue

        ground_truth = data["ground_truth"]
        top_chunk = TOP_CHUNK
        while True:
            retrived_chunks = await retrive_relevant_chunks(
                query=query,
                embedder=embedder,
                retriver=retrival,
                top_chunk=top_chunk,
            )
            chunks_to_send = []
            if retrived_chunks is None:
                logger.warning(
                    "[EVAL-RETRIVAL] NO RETRIEVED CHUNKS FOR QUERY, %s\n", query
                )
            else:
                logger.info("[EVAL-RETRIVAL] RETRIEVING CHUNKS")
                chunks_to_send = [chunk["chunk"] for chunk in retrived_chunks]

            try:
                generated_answer = await generate_the_content(
                    query=query, retrived_content=chunks_to_send, generator=generator
                )
            except GenerationError as error:
                if error.status_code == 413 and top_chunk > 4:
                    top_chunk -= 1
                    logger.warning(
                        "[EVAL-GENERATION] GENERATION REQUEST TOO LARGE; RETRYING "
                        "WITH top_chunk=%s, query=%s",
                        top_chunk,
                        query,
                    )
                    continue
                raise RuntimeError(
                    f"Generation failed for query {query!r}: {error} "
                    f"(status_code={error.status_code})"
                ) from error

            formated_query = EVALUATOR_PROMPT.format(
                question=query,
                ground_truth_answer=ground_truth,
                retrieved_chunks=chunks_to_send,
                generated_answer=generated_answer,
            )

            evaluated = await generator.LLM(
                model=evaluation_model,
                messages=[{"role": "user", "content": formated_query}],
                # api_key=env_config.EVALUATION_API_KEY,
            )

            if evaluated["type"] == "success":
                break

            if evaluated.get("status_code") == 413 and top_chunk > 4:
                top_chunk -= 1
                logger.warning(
                    "[EVAL-GENERATION] REQUEST TOO LARGE FOR QUERY; RETRYING WITH "
                    "top_chunk=%s, query=%s",
                    top_chunk,
                    query,
                )
                continue

            raise RuntimeError(
                f"Evaluation failed for query {query!r}: {evaluated['content']} "
                f"(status_code={evaluated.get('status_code')})"
            )

        raw_evaluation = evaluated.get("content")
        try:
            if not isinstance(raw_evaluation, str):
                raise TypeError("Evaluation response content is not a string")
            evaluation_result = json.loads(raw_evaluation)
        except (json.JSONDecodeError, TypeError):
            evaluation_result = (
                raw_evaluation
                if isinstance(raw_evaluation, str)
                else str(raw_evaluation)
            )
            query_scores = {}
            logger.warning(
                "[EVAL-GENERATION] INVALID EVALUATION JSON FOR QUERY %s; "
                "SAVING RAW RESPONSE WITHOUT SCORES",
                query,
            )
        else:
            query_scores = {}
            for dimension in (
                "correctness",
                "faithfulness",
                "completeness",
                "answerability",
            ):
                score = evaluation_result[dimension]["score"]
                if (
                    isinstance(score, bool)
                    or not isinstance(score, int)
                    or not 0 <= score <= 2
                ):
                    raise ValueError(
                        f"Invalid {dimension} score for query {query!r}: {score!r}"
                    )
                query_scores[dimension] = score

        result = {
            "dataset_index": None if is_custom_query else dataset_index,
            "query": query,
            "ground_truth_answer": ground_truth,
            "generated_answer": generated_answer,
            "evaluation": evaluation_result,
            "scores": query_scores,
            "top_chunk": top_chunk,
            "evaluation_model": evaluation_model,
        }
        if is_custom_query:
            per_query_results = replace_query_result(per_query_results, result)
        else:
            per_query_results.append(result)

        await save_dataset(
            build_report(per_query_results, evaluation_model), OUTPUT_FILE_PATH
        )
        if not is_custom_query:
            completed_indices.add(dataset_index)
            time.sleep(60)

    average_scores = recalculate_average_scores(INPUT_FILE_PATH)
    logger.info(
        "[EVAL-GENERATION] REPORT SAVED TO %s; RECALCULATED AVERAGES: %s",
        OUTPUT_FILE_PATH,
        average_scores["average_scores"],
    )


if __name__ == "__main__":
    asyncio.run(main())
