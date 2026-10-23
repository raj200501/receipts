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

QWEN_CODER_1_5B = LocalModel(
    name="qwen2.5-coder-1.5b-instruct-q4km",
    family="qwen",
    path=MODELS_DIR / "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
    sha256="cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046",
    source="huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF@f86cb2c1fa58255f8052cc32aeede1b7482d4361",
)

GRANITE_2B = LocalModel(
    name="granite-3.3-2b-instruct-q4km",
    family="granite",
    path=MODELS_DIR / "granite-3.3-2b-instruct-Q4_K_M.gguf",
    sha256="ac71e9e32c0bea919b409c5918f69ca74339854b0319c5065e4e9fb6d95c4852",
    source="huggingface.co/ibm-granite/granite-3.3-2b-instruct-GGUF@7cdf86ccd1f1bb3491c9b7017b033f2e51367397",
)

LOCAL_MODELS: dict[str, LocalModel] = {
    m.name: m for m in (QWEN_CODER_7B, GRANITE_8B, QWEN_CODER_1_5B, GRANITE_2B)
}
