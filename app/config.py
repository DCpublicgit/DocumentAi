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
    score_threshold: float = Field(default=0.35, alias="SCORE_THRESHOLD")
    policy_dir: str = Field(alias="POLICY_DIR")
    rerank_score_threshold: float = Field(default=0.5, alias="RERANK_SCORE_THRESHOLD")
    rerank_enabled: bool = Field(default=True, alias="RERANK_ENABLED")
    rerank_model: str = Field(default="BAAI/bge-reranker-v2-m3", alias="RERANK_MODEL")
    rerank_top_n: int = Field(default=10, alias="RERANK_TOP_N")
    query_expansion_enabled: bool = Field(default=True, alias="QUERY_EXPANSION_ENABLED")
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
    llm_max_retries: int = Field(default=5, alias="LLM_MAX_RETRIES")
    llm_retry_base_delay: float = Field(default=1.0, alias="LLM_RETRY_BASE_DELAY")
    llm_retry_max_delay: float = Field(default=30.0, alias="LLM_RETRY_MAX_DELAY")
    clause_description_max_chars: int = Field(default=80, alias="CLAUSE_DESCRIPTION_MAX_CHARS")
    gibberish_max_consonant_run: int = Field(default=5, alias="GIBBERISH_MAX_CONSONANT_RUN")


settings = Settings()
