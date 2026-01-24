# Data Directory

This directory stores persistent data for the 7-layer intelligent bot:

- `context_buffers.json` - Pending transaction state (survives restarts)
- `learning_data.json` - Error patterns, category learning, user profiles
- `embeddings_cache.json` - MiniLM embedding cache for duplicate detection

These files are auto-generated and managed by the layer system.
Do not edit manually unless you know what you're doing.
