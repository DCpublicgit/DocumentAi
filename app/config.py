from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    llm_provider: str = Field(alias="LLM_PROVIDER")
    llm_model: str = Field(alias="LLM_MODEL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    ollama_base_url: str = Field(default="http://ollama:11434/v1", alias="OLLAMA_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai", alias="GEMINI_BASE_URL"
    )
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1", alias="DEEPSEEK_BASE_URL")
    embedding_model: str = Field(alias="EMBEDDING_MODEL")
    database_url: str = Field(alias="DATABASE_URL")
    top_k: int = Field(default=5, alias="TOP_K")
    # Set 2026-10-08 from an END-TO-END eval (88 questions, gemini-3.5-flash-lite,
    # eval_results/newgate_t050_*), not from `python -m app.eval calibrate`
    # alone. Cosine similarity cannot separate on- from off-topic here (an
    # off-topic question scored 0.581, a real answerable one 0.515), and
    # calibrate scores this gate in isolation — it can't see that a false
    # pass still reaches the model's own refusal rule (SYSTEM_PROMPT rule 4),
    # while a false refuse has no second chance. At 0.50 the model refused
    # 13/13 off-topic questions and 0.52 refused one more answerable
    # question ("(BoD) ..."). Re-run the end-to-end eval, not just calibrate,
    # after any meaningful corpus or embedding-model change.
    score_threshold: float = Field(default=0.50, alias="SCORE_THRESHOLD")
    policy_dir: str = Field(alias="POLICY_DIR")
    rerank_score_threshold: float = Field(default=0.5, alias="RERANK_SCORE_THRESHOLD")
    rerank_enabled: bool = Field(default=True, alias="RERANK_ENABLED")
    rerank_model: str = Field(default="BAAI/bge-reranker-v2-m3", alias="RERANK_MODEL")
    rerank_top_n: int = Field(default=10, alias="RERANK_TOP_N")
    # Off by default since 2026-10-08: on the 88-question eval it changed
    # accuracy by one question either way (within noise), while adding a
    # serial LLM call (~1.3 s median) and ~10% of per-question cost, and its
    # rephrasings vary run to run, so the excerpts an answer rests on did too.
    query_expansion_enabled: bool = Field(default=False, alias="QUERY_EXPANSION_ENABLED")
    query_expansion_provider: str = Field(
        default="anthropic", alias="QUERY_EXPANSION_PROVIDER"
    )
    query_expansion_model: str = Field(
        default="claude-haiku-4-5-20251001", alias="QUERY_EXPANSION_MODEL"
    )
    # Default 1, not 2: each rephrasing is a fresh, temperature-sampled LLM
    # generation, so more of them means more chances one drifts semantically
    # broader than the original question. RRF sums scores per exact
    # (file, version, chunk_index), not per document, so a single drifted
    # rephrasing that favors a competing chunk can occasionally outrank the
    # correct one even when every phrasing's raw candidate pool still
    # contains it — see Docs/DATA_CONTRACT.md's query expansion note.
    query_expansion_n: int = Field(default=1, alias="QUERY_EXPANSION_N")
    chunk_size_tokens: int = Field(default=500, alias="CHUNK_SIZE_TOKENS")
    embed_batch_size: int = Field(default=32, alias="EMBED_BATCH_SIZE")
    retrieval_candidate_n: int = Field(default=20, alias="RETRIEVAL_CANDIDATE_N")
    llm_max_tokens: int = Field(default=1024, alias="LLM_MAX_TOKENS")
    warm_up_models_enabled: bool = Field(default=True, alias="WARM_UP_MODELS_ENABLED")
    # Asks the provider to append a usage chunk to a streamed answer
    # (stream_options.include_usage) so the audit table can record real token
    # counts for the main, streamed path. Off by default: not every
    # OpenAI-compatible endpoint is known to accept the option, and a 400
    # here would break the live answer path. Enable per provider after
    # verifying it with one real call.
    llm_stream_usage: bool = Field(default=False, alias="LLM_STREAM_USAGE")
    llm_max_retries: int = Field(default=5, alias="LLM_MAX_RETRIES")
    llm_retry_base_delay: float = Field(default=1.0, alias="LLM_RETRY_BASE_DELAY")
    llm_retry_max_delay: float = Field(default=30.0, alias="LLM_RETRY_MAX_DELAY")
    clause_description_max_chars: int = Field(default=80, alias="CLAUSE_DESCRIPTION_MAX_CHARS")
    gibberish_max_consonant_run: int = Field(default=5, alias="GIBBERISH_MAX_CONSONANT_RUN")
    # Own provider/model, same reasoning as query expansion above: condensing
    # a followup into a standalone query is orthogonal to which model
    # generates the final answer, and must not require an Anthropic key on
    # an Ollama-only deployment.
    query_rewrite_enabled: bool = Field(default=True, alias="QUERY_REWRITE_ENABLED")
    query_rewrite_provider: str = Field(default="anthropic", alias="QUERY_REWRITE_PROVIDER")
    query_rewrite_model: str = Field(
        default="claude-haiku-4-5-20251001", alias="QUERY_REWRITE_MODEL"
    )


settings = Settings()
