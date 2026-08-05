from pydantic import BaseModel


class LlmField(BaseModel):
    name: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""
    options: list[str] | None = None


class LlmProviderDefinition(BaseModel):
    slug: str
    display_name: str
    logo_key: str
    docs_url: str
    description: str
    fields: list[LlmField]
    default_model: str
    default_embedding_model: str | None = None
    wired: bool


def _api_key(placeholder: str) -> LlmField:
    return LlmField(name="api_key", label="API key", secret=True, placeholder=placeholder)


def _model(default: str, options: list[str]) -> LlmField:
    return LlmField(
        name="model",
        label="Model",
        secret=False,
        required=False,
        placeholder=default,
        options=options,
    )


def _base_url(default: str) -> LlmField:
    return LlmField(
        name="base_url",
        label="Base URL",
        secret=False,
        required=False,
        placeholder=default,
    )


def _embedding_model(default: str, options: list[str]) -> LlmField:
    return LlmField(
        name="embedding_model",
        label="Embedding model",
        secret=False,
        required=False,
        placeholder=default,
        options=options,
    )


OPENAI_MODELS = [
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
    "o3-mini",
    "o1",
]

ANTHROPIC_MODELS = [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

GOOGLE_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

OLLAMA_MODELS = [
    "llama3.1:8b",
    "qwen2.5:7b",
    "llama3.2:3b",
    "qwen2.5:3b",
    "qwen2.5:14b",
    "qwen2.5-coder:14b",
]

OLLAMA_EMBED_MODELS = [
    "nomic-embed-text",
    "mxbai-embed-large",
    "all-minilm",
]

OPENAI_EMBED_MODELS = [
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-ada-002",
]


def catalog() -> list[LlmProviderDefinition]:
    return [
        LlmProviderDefinition(
            slug="openai",
            display_name="OpenAI",
            logo_key="openai",
            docs_url="https://platform.openai.com/docs/",
            description="Powers chat tool-calling and the Docs agent when configured.",
            fields=[
                _api_key("sk-…"),
                _model("gpt-4.1-mini", OPENAI_MODELS),
                _embedding_model("text-embedding-3-small", OPENAI_EMBED_MODELS),
            ],
            default_model="gpt-4.1-mini",
            default_embedding_model="text-embedding-3-small",
            wired=True,
        ),
        LlmProviderDefinition(
            slug="ollama",
            display_name="Ollama (local)",
            logo_key="ollama",
            docs_url="https://ollama.com/",
            description="Runs chat, summaries, and embeddings against a local OpenAI-compatible Ollama server.",
            fields=[
                _base_url("http://localhost:11434/v1"),
                _model("llama3.1:8b", OLLAMA_MODELS),
                _embedding_model("nomic-embed-text", OLLAMA_EMBED_MODELS),
            ],
            default_model="llama3.1:8b",
            default_embedding_model="nomic-embed-text",
            wired=True,
        ),
        LlmProviderDefinition(
            slug="anthropic",
            display_name="Anthropic (Claude)",
            logo_key="anthropic",
            docs_url="https://docs.anthropic.com/",
            description="Stored for future use — chat agent does not yet call Claude.",
            fields=[_api_key("sk-ant-…"), _model("claude-sonnet-4-6", ANTHROPIC_MODELS)],
            default_model="claude-sonnet-4-6",
            wired=False,
        ),
        LlmProviderDefinition(
            slug="google",
            display_name="Google (Gemini)",
            logo_key="google",
            docs_url="https://ai.google.dev/docs",
            description="Stored for future use — chat agent does not yet call Gemini.",
            fields=[_api_key("AIza…"), _model("gemini-1.5-pro", GOOGLE_MODELS)],
            default_model="gemini-1.5-pro",
            wired=False,
        ),
    ]


CATALOG_BY_SLUG = {item.slug: item for item in catalog()}
