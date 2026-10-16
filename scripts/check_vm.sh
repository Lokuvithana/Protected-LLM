#!/usr/bin/env bash
# Step 1: check the Ubuntu VM and recommend an Ollama model.
# Usage: bash scripts/check_vm.sh
set -u
line() { printf '%s\n' "------------------------------------------------------------"; }

line; echo "Protected LLM: VM check"; line
echo "OS:        $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
echo "Kernel:    $(uname -r)   Arch: $(uname -m)"
CORES=$(nproc)
echo "CPU cores: $CORES   Model: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)"
if grep -qw avx2 /proc/cpuinfo; then AVX="avx2"; elif grep -qw avx /proc/cpuinfo; then AVX="avx"; else AVX="none"; fi
echo "AVX:       $AVX   (Ollama is much faster with AVX2)"

MEM_TOTAL=$(awk '/MemTotal/ {printf "%.1f", $2/1048576}' /proc/meminfo)
MEM_AVAIL=$(awk '/MemAvailable/ {printf "%.1f", $2/1048576}' /proc/meminfo)
SWAP=$(awk '/SwapTotal/ {printf "%.1f", $2/1048576}' /proc/meminfo)
echo "RAM:       ${MEM_TOTAL} GB total, ${MEM_AVAIL} GB available, swap ${SWAP} GB"

DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)
DISK_FREE=$(df -BG --output=avail "$(dirname "$DOCKER_ROOT")" 2>/dev/null | tail -1 | tr -dc '0-9')
echo "Disk:      ${DISK_FREE:-?} GB free for Docker ($DOCKER_ROOT)"

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  echo "GPU:       $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
  GPU=yes
else
  echo "GPU:       none detected (CPU only is fine for small models)"; GPU=no
fi
line
echo "Docker:    $(docker --version 2>/dev/null || echo 'NOT FOUND')"
echo "Compose:   $(docker compose version 2>/dev/null || echo 'NOT FOUND: install the docker-compose-plugin')"
if ! docker info >/dev/null 2>&1; then
  echo "WARNING:   cannot talk to Docker. Run: sudo usermod -aG docker \$USER  then log out and in."
fi
line
echo "Ports in use (need 8080, 8010, 5432, 11434 free):"
in_use() {
  if command -v ss >/dev/null 2>&1; then ss -ltn | awk '{print $4}' | grep -qE "[:.]$1$"
  else (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; fi
}
for p in 8080 8010 5432 11434; do
  if in_use "$p"; then echo "  $p  IN USE"; fi
done
echo "  (nothing listed = all free)"
line

# Model recommendation. The rest of the stack needs about 1 GB.
avail=${MEM_AVAIL%.*}
if [ "$avail" -lt 5 ]; then
  MODEL="qwen2.5:1.5b"; WHY="less than 5 GB available"
elif [ "$avail" -lt 11 ]; then
  MODEL="qwen2.5:3b"; WHY="5 to 11 GB available"
else
  MODEL="qwen2.5:7b"; WHY="11 GB or more available"
fi
echo "Recommended OLLAMA_MODEL=$MODEL  ($WHY)"
[ "${DISK_FREE:-0}" -lt 15 ] && echo "Low disk: images + model need about 10 to 15 GB."
[ "$CORES" -lt 4 ] && echo "Fewer than 4 cores: answers will be slow; prefer qwen2.5:1.5b."
[ "$GPU" = "yes" ] && echo "GPU found: start with -f docker-compose.gpu.yml (needs NVIDIA Container Toolkit)."
line
