# Marks app/providers as a package. The ModelProvider layer lives here:
#   base.py    — the interface (Protocol) + the data types that cross it
#   mock_provider.py    — zero-cost canned streams (used when MOCK_LLM=true)
#   litellm_provider.py — real streaming model calls via LiteLLM
#   factory.py — picks the right provider based on settings
