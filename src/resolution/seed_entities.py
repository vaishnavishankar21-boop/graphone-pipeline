"""
Seed database of known canonical AI/startup entities.

Per the assignment spec: "Map extracted entities against a seed list of
known canonical entities (you may mock a small database of 50 known AI
startups)." This is that mock database -- 50 real, well-known AI
companies, each with common name variants (legal suffixes, spacing,
punctuation differences) that real-world sources might use when
referring to them.

This is intentionally small and hand-curated (not itself scraped) --
it's the reference/ground-truth list the resolver matches AGAINST, not
data to be validated itself.
"""

from __future__ import annotations

# canonical_name -> list of known alternate forms seen "in the wild"
SEED_ENTITIES: dict[str, list[str]] = {
    "OpenAI": ["OpenAI, Inc.", "Open AI", "OpenAI Inc", "Open-AI", "OpenAI Inc."],
    "Anthropic": ["Anthropic PBC", "Anthropic, Inc.", "Anthropic AI", "Anthropic Inc"],
    "Google DeepMind": ["DeepMind", "DeepMind Technologies", "Google Deep Mind"],
    "Mistral AI": ["Mistral", "Mistral AI SAS", "MistralAI"],
    "Cohere": ["Cohere Inc", "Cohere AI", "Cohere Technologies", "Cohere Inc."],
    "Stability AI": ["Stability AI Ltd", "StabilityAI", "Stability.ai"],
    "Hugging Face": ["HuggingFace", "Hugging Face Inc", "Hugging Face, Inc."],
    "Scale AI": ["Scale", "Scale AI Inc", "Scale AI, Inc."],
    "Databricks": ["Databricks Inc", "Data Bricks", "Databricks, Inc."],
    "Perplexity AI": ["Perplexity", "Perplexity.ai", "Perplexity Inc"],
    "Character.AI": ["Character AI", "CharacterAI", "Character.ai"],
    "Inflection AI": ["Inflection", "Inflection AI Inc"],
    "Adept AI": ["Adept", "Adept AI Labs"],
    "Runway": ["Runway AI", "Runway ML", "RunwayML"],
    "Midjourney": ["Midjourney Inc", "Mid Journey"],
    "ElevenLabs": ["Eleven Labs", "ElevenLabs Inc", "11Labs"],
    "Together AI": ["Together", "Together Computer", "Together.ai"],
    "Groq": ["Groq Inc", "Groq, Inc."],
    "Cerebras Systems": ["Cerebras", "Cerebras Systems Inc"],
    "SambaNova Systems": ["SambaNova", "SambaNova Systems Inc"],
    "Glean": ["Glean Technologies", "Glean Inc"],
    "Harvey": ["Harvey AI", "Harvey AI Inc"],
    "Sierra": ["Sierra AI", "Sierra Platform"],
    "Replit": ["Replit Inc", "Repl.it"],
    "Anysphere": ["Cursor", "Cursor AI", "Anysphere Inc"],
    "Vercel": ["Vercel Inc"],
    "LangChain": ["LangChain Inc", "Lang Chain"],
    "Pinecone": ["Pinecone Systems", "Pinecone Inc"],
    "Weights & Biases": ["Weights and Biases", "WandB", "W&B", "Weights&Biases"],
    "Snorkel AI": ["Snorkel", "Snorkel AI Inc"],
    "Tabnine": ["Tab Nine", "Tabnine Inc"],
    "Jasper AI": ["Jasper", "Jasper.ai"],
    "Writer": ["Writer Inc", "Writer AI"],
    "Synthesia": ["Synthesia Ltd", "Synthesia AI"],
    "Rasa": ["Rasa Technologies", "Rasa AI"],
    "AssemblyAI": ["Assembly AI", "AssemblyAI Inc"],
    "Deepgram": ["Deep Gram", "Deepgram Inc"],
    "Voiceflow": ["Voice Flow", "Voiceflow Inc"],
    "Landing AI": ["LandingAI", "Landing.AI"],
    "Codeium": ["Windsurf", "Windsurf AI", "Codeium Inc"],
    "Fireworks AI": ["Fireworks", "Fireworks.ai"],
    "Anyscale": ["Any Scale", "Anyscale Inc"],
    "Weaviate": ["Weaviate B.V.", "Weaviate Inc"],
    "Chroma": ["ChromaDB", "Chroma Inc"],
    "LlamaIndex": ["Llama Index", "GPT Index"],
    "Contextual AI": ["Contextual", "Contextual AI Inc"],
    "Imbue": ["Generally Intelligent", "Imbue AI"],
    "Reka AI": ["Reka", "Reka AI Inc"],
    "World Labs": ["World Labs Inc"],
    "Physical Intelligence": ["Physical Intelligence Inc", "Pi Robotics"],
}

assert len(SEED_ENTITIES) == 50, f"Expected 50 seed entities, got {len(SEED_ENTITIES)}"

