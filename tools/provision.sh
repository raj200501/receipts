#!/bin/bash
# Provision a fresh container for receipts (idempotent). DECISIONS D22, D23.
# Installs bubblewrap, starts the Docker daemon when possible, builds the
# llama-cpp-python server in /opt/receipts-llm, and downloads the pinned GGUF
# models into /opt/receipts-models, verifying each against its Hugging Face
# LFS sha256. It never writes inside the repository except runs/ (git-ignored).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNS="$ROOT/runs/provision"
mkdir -p "$RUNS" /opt/receipts-models

if ! command -v bwrap >/dev/null 2>&1; then
  apt-get install -y bubblewrap >"$RUNS/apt.log" 2>&1 || {
    apt-get update >>"$RUNS/apt.log" 2>&1 && apt-get install -y bubblewrap >>"$RUNS/apt.log" 2>&1
  }
fi
bwrap --unshare-all --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp true && echo "bwrap: ok"

if command -v dockerd >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then
  rm -f /var/run/docker.pid
  nohup dockerd --iptables=false >"$RUNS/dockerd.log" 2>&1 &
  for _ in $(seq 1 20); do docker info >/dev/null 2>&1 && break; sleep 1; done
fi
docker info --format 'docker: {{.ServerVersion}}' 2>/dev/null || echo "docker: unavailable (bwrap is used)"

LLAMA_CPP_PYTHON=0.3.36
if ! /opt/receipts-llm/bin/python -c "import llama_cpp.server" >/dev/null 2>&1; then
  uv venv --python 3.11 /opt/receipts-llm
  CMAKE_ARGS="-DGGML_NATIVE=ON -DLLAMA_CURL=OFF" CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" \
    uv pip install --python /opt/receipts-llm/bin/python --no-binary llama-cpp-python \
    "llama-cpp-python[server]==$LLAMA_CPP_PYTHON" >"$RUNS/llama-build.log" 2>&1
fi
/opt/receipts-llm/bin/python -c "import llama_cpp; print('llama-cpp-python:', llama_cpp.__version__)"

fetch() {  # repo revision file
  local repo=$1 rev=$2 file=$3 out=/opt/receipts-models/$3
  if [ ! -f "$out" ]; then
    curl -sS -L --retry 5 -C - -o "$out.part" "https://huggingface.co/$repo/resolve/$rev/$file"
    mv "$out.part" "$out"
  fi
  local want got
  want=$(curl -sS "https://huggingface.co/api/models/$repo/tree/$rev" |
    python3 -c "import json,sys; print(next(f['lfs']['oid'] for f in json.load(sys.stdin) if f['path']=='$file'))")
  got=$(sha256sum "$out" | cut -d' ' -f1)
  if [ "$want" != "$got" ]; then echo "HASH MISMATCH $file"; exit 1; fi
  echo "model: $file sha256=$got"
}
fetch Qwen/Qwen2.5-Coder-7B-Instruct-GGUF 13fb94bfda8c8cf22497dc57b78f391a9acb426a \
  qwen2.5-coder-7b-instruct-q4_k_m.gguf
fetch ibm-granite/granite-3.3-8b-instruct-GGUF e40e9dd739c7be00fa965c16ce167088190ce114 \
  granite-3.3-8b-instruct-Q4_K_M.gguf
fetch Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF f86cb2c1fa58255f8052cc32aeede1b7482d4361 \
  qwen2.5-coder-1.5b-instruct-q4_k_m.gguf
fetch ibm-granite/granite-3.3-2b-instruct-GGUF 7cdf86ccd1f1bb3491c9b7017b033f2e51367397 \
  granite-3.3-2b-instruct-Q4_K_M.gguf
echo "PROVISION: OK"
