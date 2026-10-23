"""The pinned local models (DECISIONS D23, docs/DATA.md)."""

from __future__ import annotations

from pathlib import Path

from receipts.client.server import LocalModel

MODELS_DIR = Path("/opt/receipts-models")

QWEN_CODER_7B = LocalModel(
    name="qwen2.5-coder-7b-instruct-q4km",
    family="qwen",
    path=MODELS_DIR / "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
    sha256="509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c",
    source="huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF@13fb94bfda8c8cf22497dc57b78f391a9acb426a",
)

GRANITE_8B = LocalModel(
    name="granite-3.3-8b-instruct-q4km",
    family="granite",
    path=MODELS_DIR / "granite-3.3-8b-instruct-Q4_K_M.gguf",
    sha256="77bcee066a76dcdd10d0d123c87e32c8ec2c74e31b6ffd87ebee49c9ac215dca",
    source="huggingface.co/ibm-granite/granite-3.3-8b-instruct-GGUF@e40e9dd739c7be00fa965c16ce167088190ce114",
)

LOCAL_MODELS: dict[str, LocalModel] = {m.name: m for m in (QWEN_CODER_7B, GRANITE_8B)}
