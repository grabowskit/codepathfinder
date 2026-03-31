#!/usr/bin/env bash
# =============================================================================
# CodePathfinder Interactive Setup Script
# =============================================================================
# Usage:
#   ./setup.sh                     Interactive setup (default)
#   ./setup.sh --skip-build        Skip docker compose build
#   ./setup.sh --skip-start        Generate config files only, don't start services
#   ./setup.sh --non-interactive   Read answers from SETUP_* env vars or answers.conf
#
# Future Onboarding UI integration:
#   Generate answers.conf and call: ./setup.sh --non-interactive
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Script directory / repo root
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------
SKIP_BUILD=false
SKIP_START=false
NON_INTERACTIVE=false

for arg in "$@"; do
  case "$arg" in
    --skip-build)       SKIP_BUILD=true ;;
    --skip-start)       SKIP_START=true ;;
    --non-interactive)  NON_INTERACTIVE=true ;;
    -h|--help)
      grep '^#' "$0" | head -12 | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Colors & formatting
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

tolower() { echo "$1" | tr '[:upper:]' '[:lower:]'; }

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "  ${RED}✗${NC} $*"; }
info() { echo -e "  ${BLUE}→${NC} $*"; }
hdr()  { echo -e "\n${BOLD}$*${NC}"; }

# ---------------------------------------------------------------------------
# Cross-platform sed wrapper (macOS BSD vs Linux GNU)
# ---------------------------------------------------------------------------
sed_inplace() {
  local pattern="$1"
  local file="$2"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "$pattern" "$file"
  else
    sed -i "$pattern" "$file"
  fi
}

# ---------------------------------------------------------------------------
# Secret generation (pure bash + openssl — no Python required on host)
# ---------------------------------------------------------------------------
gen_secret_base64() {
  openssl rand -base64 32 | tr -d '/+=' | cut -c -32
}

gen_secret_long() {
  # ~50 alphanumeric chars, suitable for DJANGO_SECRET_KEY
  openssl rand -base64 38 | tr -d '/+=' | cut -c -50
}

gen_hex() {
  local bytes="${1:-16}"
  openssl rand -hex "$bytes"
}

# ---------------------------------------------------------------------------
# Spinner for long-running operations
# ---------------------------------------------------------------------------
SPINNER_PID=""
spinner_start() {
  local msg="${1:-Working...}"
  local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
  (
    i=0
    while true; do
      printf "\r  ${BLUE}%s${NC} %s " "${frames[$((i % ${#frames[@]}))]}" "$msg"
      sleep 0.1
      ((i++))
    done
  ) &
  SPINNER_PID=$!
  disown "$SPINNER_PID" 2>/dev/null || true
}

spinner_stop() {
  if [[ -n "$SPINNER_PID" ]]; then
    kill "$SPINNER_PID" 2>/dev/null || true
    SPINNER_PID=""
    printf "\r%-80s\r" " "
  fi
}

# ---------------------------------------------------------------------------
# answers.conf — persists user choices across re-runs
# ---------------------------------------------------------------------------
ANSWERS_FILE="$REPO_ROOT/answers.conf"

answers_get() {
  local key="$1"
  local default="${2:-}"
  # SETUP_* env vars take highest precedence (non-interactive mode)
  local env_key="SETUP_${key}"
  if [[ -n "${!env_key:-}" ]]; then
    echo "${!env_key}"
    return
  fi
  if [[ -f "$ANSWERS_FILE" ]]; then
    local val
    val=$(grep "^${key}=" "$ANSWERS_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -n "$val" ]]; then
      echo "$val"
      return
    fi
  fi
  echo "$default"
}

answers_set() {
  local key="$1"
  local value="$2"
  if [[ -f "$ANSWERS_FILE" ]] && grep -q "^${key}=" "$ANSWERS_FILE" 2>/dev/null; then
    sed_inplace "s|^${key}=.*|${key}=${value}|" "$ANSWERS_FILE"
  else
    echo "${key}=${value}" >> "$ANSWERS_FILE"
  fi
}

# Parse a value from an existing .env file
parse_env_file() {
  local file="$1"
  local key="$2"
  local default="${3:-}"
  if [[ -f "$file" ]]; then
    local val
    val=$(grep "^${key}=" "$file" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -n "$val" ]]; then
      echo "$val"
      return
    fi
  fi
  echo "$default"
}

# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------
# prompt VAR_NAME "label" "default" ["true" for secret]
prompt() {
  local var_name="$1"
  local prompt_text="$2"
  local default="${3:-}"
  local secret="${4:-false}"

  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    local val
    val=$(answers_get "$var_name" "$default")
    printf -v "$var_name" '%s' "$val"
    return
  fi

  local display_default=""
  if [[ -n "$default" ]]; then
    if [[ "$secret" == "true" ]]; then
      display_default=" [****]"
    else
      display_default=" [$default]"
    fi
  fi

  if [[ "$secret" == "true" ]]; then
    read -r -s -p "  ${prompt_text}${display_default}: " "$var_name"
    echo ""
  else
    read -r -p "  ${prompt_text}${display_default}: " "$var_name"
  fi

  if [[ -z "${!var_name}" && -n "$default" ]]; then
    printf -v "$var_name" '%s' "$default"
  fi
}

# prompt_yn VAR_NAME "question" "y"|"n"
prompt_yn() {
  local var_name="$1"
  local prompt_text="$2"
  local default="${3:-y}"

  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    local val
    val=$(answers_get "$var_name" "$default")
    printf -v "$var_name" '%s' "$val"
    return
  fi

  local choices
  if [[ "$default" == "y" ]]; then
    choices="[Y/n]"
  else
    choices="[y/N]"
  fi

  read -r -p "  ${prompt_text} ${choices}: " "$var_name"
  if [[ -z "${!var_name}" ]]; then
    printf -v "$var_name" '%s' "$default"
  fi
}

# =============================================================================
# PHASE 1: Prerequisites Check
# =============================================================================
MKCERT_AVAILABLE=false

phase1_prerequisites() {
  hdr "Phase 1: Prerequisites Check"
  echo ""

  local all_ok=true

  # Docker daemon
  if docker info >/dev/null 2>&1; then
    ok "Docker daemon is running"
  else
    err "Docker daemon is not running — please start Docker"
    all_ok=false
  fi

  # Docker Compose v2
  if docker compose version >/dev/null 2>&1; then
    local compose_ver
    compose_ver=$(docker compose version --short 2>/dev/null || echo "unknown")
    ok "Docker Compose v2 ($compose_ver)"
  else
    err "Docker Compose v2 not found (need: docker compose, not docker-compose)"
    all_ok=false
  fi

  # Git
  if git --version >/dev/null 2>&1; then
    ok "Git ($(git --version | awk '{print $3}'))"
  else
    err "Git not found"
    all_ok=false
  fi

  # openssl
  if openssl version >/dev/null 2>&1; then
    ok "openssl ($(openssl version | awk '{print $2}'))"
  else
    err "openssl not found — required for secret generation"
    all_ok=false
  fi

  # mkcert (optional)
  if command -v mkcert >/dev/null 2>&1; then
    MKCERT_AVAILABLE=true
    ok "mkcert available — HTTPS recommended"
  else
    MKCERT_AVAILABLE=false
    warn "mkcert not found — HTTPS will not be available"
    info "macOS: brew install mkcert && mkcert -install"
    info "Linux: https://github.com/FiloSottile/mkcert#installation"
  fi

  echo ""
  echo "  Checking port availability:"
  # Associative arrays not supported in bash 3 (macOS default) — use parallel arrays
  local port_list=(5432 8000 8443 3080 3443 9200 5601 27017 7700)
  local port_labels=("PostgreSQL" "Web HTTP" "Web HTTPS" "LibreChat HTTP" "LibreChat HTTPS" "Elasticsearch" "Kibana" "MongoDB" "Meilisearch")
  local i
  for i in "${!port_list[@]}"; do
    local port="${port_list[$i]}"
    local name="${port_labels[$i]}"
    if ! (echo >/dev/tcp/localhost/"$port") 2>/dev/null; then
      ok "  $port ($name) is free"
    else
      warn "  $port ($name) is in use — may conflict"
    fi
  done

  if [[ "$all_ok" == "false" ]]; then
    echo ""
    err "Required prerequisites are missing. Please install them and re-run."
    exit 1
  fi
}

# =============================================================================
# PHASE 2: Interactive Configuration
# =============================================================================
USE_HTTPS=""
ES_MODE=""
ES_PASSWORD=""
ES_CLOUD_ID=""
ES_API_KEY=""
LLM_SELECTION=""
OPENAI_API_KEY=""
ANTHROPIC_API_KEY=""
AZURE_API_KEY=""
AZURE_INSTANCE_NAME=""
AZURE_API_VERSION="2024-12-01-preview"
GEMINI_API_KEY=""
BEDROCK_ACCESS_KEY=""
BEDROCK_SECRET_KEY=""
BEDROCK_REGION="us-east-2"
GOOGLE_OAUTH=""
GOOGLE_CLIENT_ID=""
GOOGLE_CLIENT_SECRET=""
GITHUB_TOKEN=""

phase2_interactive_config() {
  hdr "Phase 2: Interactive Configuration"
  echo ""
  [[ "$NON_INTERACTIVE" != "true" ]] && info "Press Enter to accept defaults. Existing values shown in [brackets]."
  echo ""

  # ── HTTPS ───────────────────────────────────────────────────────────────
  echo -e "  ${BOLD}HTTPS Setup${NC}"
  local https_default
  https_default=$(answers_get "USE_HTTPS" "")
  if [[ -z "$https_default" ]]; then
    https_default=$([[ "$MKCERT_AVAILABLE" == "true" ]] && echo "y" || echo "n")
  fi

  if [[ "$MKCERT_AVAILABLE" == "false" ]]; then
    warn "mkcert not available — defaulting to HTTP"
    USE_HTTPS="n"
  else
    prompt_yn "USE_HTTPS" "Enable HTTPS with mkcert (recommended)?" "$https_default"
  fi
  answers_set "USE_HTTPS" "$USE_HTTPS"
  echo ""

  # ── Elasticsearch ────────────────────────────────────────────────────────
  echo -e "  ${BOLD}Elasticsearch${NC}"
  echo "    1) Local Docker (default — quick start)"
  echo "    2) Elastic Cloud"
  echo "    3) Skip — no code indexing"
  echo ""

  local es_default
  es_default=$(answers_get "ES_MODE" "1")
  # Detect existing cloud config
  local existing_cloud
  existing_cloud=$(parse_env_file ".env" "ELASTICSEARCH_CLOUD_ID" "")
  if [[ -n "$existing_cloud" ]]; then
    es_default="2"
  fi

  local es_choice
  prompt "es_choice" "Elasticsearch mode (1/2/3)" "$es_default"
  case "$es_choice" in
    2) ES_MODE="cloud" ;;
    3) ES_MODE="skip" ;;
    *) ES_MODE="local" ;;
  esac
  answers_set "ES_MODE" "$es_choice"

  if [[ "$ES_MODE" == "local" ]]; then
    local existing_es_pass
    existing_es_pass=$(parse_env_file ".env" "ELASTICSEARCH_PASSWORD" "")
    if [[ -n "$existing_es_pass" ]]; then
      info "Using existing Elasticsearch password"
      ES_PASSWORD="$existing_es_pass"
    else
      echo ""
      echo "    Enter a password for the local Elasticsearch 'elastic' user,"
      echo "    or press Enter to auto-generate one."
      prompt "ES_PASSWORD" "Elasticsearch password" "" "true"
      if [[ -z "$ES_PASSWORD" ]]; then
        ES_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=')
        info "Auto-generated Elasticsearch password"
      fi
    fi
  elif [[ "$ES_MODE" == "cloud" ]]; then
    local ex_cloud_id
    ex_cloud_id=$(parse_env_file ".env" "ELASTICSEARCH_CLOUD_ID" "")
    local ex_api_key
    ex_api_key=$(parse_env_file ".env" "ELASTICSEARCH_API_KEY" "")
    prompt "ES_CLOUD_ID" "Elastic Cloud ID" "$ex_cloud_id"
    prompt "ES_API_KEY" "Elastic Cloud API Key" "$ex_api_key" "true"
  fi
  echo ""

  # ── LLM Providers ────────────────────────────────────────────────────────
  echo -e "  ${BOLD}LLM Providers${NC} (optional — LibreChat starts without API keys)"
  echo "    Enter comma-separated numbers or press Enter to skip:"
  echo "    1) OpenAI"
  echo "    2) Anthropic"
  echo "    3) Azure OpenAI"
  echo "    4) Google Gemini"
  echo "    5) AWS Bedrock"
  echo ""

  local llm_default
  llm_default=$(answers_get "LLM_SELECTION" "")
  prompt "LLM_SELECTION" "Providers to configure (e.g. 1,2)" "$llm_default"
  answers_set "LLM_SELECTION" "$LLM_SELECTION"

  IFS=',' read -ra provider_nums <<< "${LLM_SELECTION:-}"
  for num in "${provider_nums[@]:-}"; do
    num="${num// /}"
    case "$num" in
      1)
        local ex_openai
        ex_openai=$(parse_env_file "chat-config/.env" "OPENAI_API_KEY" "")
        prompt "OPENAI_API_KEY" "OpenAI API Key" "$ex_openai" "true"
        ;;
      2)
        local ex_anthropic
        ex_anthropic=$(parse_env_file "chat-config/.env" "ANTHROPIC_API_KEY" "")
        prompt "ANTHROPIC_API_KEY" "Anthropic API Key" "$ex_anthropic" "true"
        ;;
      3)
        local ex_azure ex_inst ex_ver
        ex_azure=$(parse_env_file "chat-config/.env" "AZURE_API_KEY" "")
        ex_inst=$(answers_get "AZURE_INSTANCE_NAME" "")
        ex_ver=$(answers_get "AZURE_API_VERSION" "2024-12-01-preview")
        prompt "AZURE_API_KEY" "Azure OpenAI API Key" "$ex_azure" "true"
        prompt "AZURE_INSTANCE_NAME" "Azure OpenAI Instance Name" "$ex_inst"
        prompt "AZURE_API_VERSION" "Azure OpenAI API Version" "$ex_ver"
        answers_set "AZURE_INSTANCE_NAME" "$AZURE_INSTANCE_NAME"
        answers_set "AZURE_API_VERSION" "$AZURE_API_VERSION"
        ;;
      4)
        local ex_gemini
        ex_gemini=$(parse_env_file "chat-config/.env" "GEMINI_API_KEY" "")
        prompt "GEMINI_API_KEY" "Google Gemini API Key" "$ex_gemini" "true"
        ;;
      5)
        local ex_bk_key ex_bk_sec ex_bk_reg
        ex_bk_key=$(parse_env_file "chat-config/.env" "BEDROCK_AWS_ACCESS_KEY_ID" "")
        ex_bk_sec=$(parse_env_file "chat-config/.env" "BEDROCK_AWS_SECRET_ACCESS_KEY" "")
        ex_bk_reg=$(parse_env_file "chat-config/.env" "BEDROCK_AWS_DEFAULT_REGION" "us-east-2")
        prompt "BEDROCK_ACCESS_KEY" "AWS Bedrock Access Key ID" "$ex_bk_key"
        prompt "BEDROCK_SECRET_KEY" "AWS Bedrock Secret Access Key" "$ex_bk_sec" "true"
        prompt "BEDROCK_REGION" "AWS Bedrock Region" "$ex_bk_reg"
        ;;
    esac
  done

  if [[ -z "$LLM_SELECTION" ]]; then
    warn "No LLM providers configured. Chat won't work until API keys are added."
    info "Add keys later in chat-config/.env and restart: docker compose restart librechat"
  fi
  echo ""

  # ── Google OAuth ─────────────────────────────────────────────────────────
  echo -e "  ${BOLD}Google OAuth${NC} (optional — enables Google login)"
  local oauth_default
  oauth_default=$(answers_get "GOOGLE_OAUTH" "n")
  local ex_gcid
  ex_gcid=$(parse_env_file ".env" "GOOGLE_CLIENT_ID" "")
  [[ -n "$ex_gcid" ]] && oauth_default="y"

  prompt_yn "GOOGLE_OAUTH" "Configure Google OAuth?" "$oauth_default"
  answers_set "GOOGLE_OAUTH" "$GOOGLE_OAUTH"

  if [[ "$(tolower "$GOOGLE_OAUTH")" == "y" ]]; then
    local ex_gcsecret
    ex_gcsecret=$(parse_env_file ".env" "GOOGLE_CLIENT_SECRET" "")
    prompt "GOOGLE_CLIENT_ID"     "Google Client ID"     "$ex_gcid"
    prompt "GOOGLE_CLIENT_SECRET" "Google Client Secret" "$ex_gcsecret" "true"
  fi
  echo ""

  # ── GitHub Token ─────────────────────────────────────────────────────────
  echo -e "  ${BOLD}GitHub Token${NC} (optional — for indexing private repos)"
  local gh_default
  gh_default=$(answers_get "GITHUB_TOKEN" "")
  prompt "GITHUB_TOKEN" "GitHub Personal Access Token (Enter to skip)" "$gh_default" "true"
  [[ -n "$GITHUB_TOKEN" ]] && answers_set "GITHUB_TOKEN" "$GITHUB_TOKEN"
  echo ""

  ok "Configuration captured"
}

# =============================================================================
# PHASE 3: Auto-Generate Secrets
# =============================================================================
DJANGO_SECRET_KEY=""
CPF_INTERNAL_SERVICE_SECRET=""
OIDC_RSA_PRIVATE_KEY=""
CREDS_KEY=""
CREDS_IV=""
JWT_SECRET=""
JWT_REFRESH_SECRET=""
OPENID_SESSION_SECRET=""
MEILI_MASTER_KEY=""
OPENID_CLIENT_ID=""
OPENID_CLIENT_SECRET=""
INSTALLATION_ID=""

phase3_generate_secrets() {
  hdr "Phase 3: Auto-Generate Secrets"
  echo ""

  # INSTALLATION_ID — stable UUID per installation (anonymous, never linked to account)
  local ex_iid
  ex_iid=$(parse_env_file ".env" "INSTALLATION_ID" "")
  if [[ -z "$ex_iid" ]]; then
    local raw
    raw=$(gen_hex 16)
    INSTALLATION_ID="${raw:0:8}-${raw:8:4}-4${raw:13:3}-8${raw:17:3}-${raw:20:12}"
    info "Generated INSTALLATION_ID"
  else
    INSTALLATION_ID="$ex_iid"
    info "Preserved existing INSTALLATION_ID"
  fi

  # DJANGO_SECRET_KEY — preserve if not a known placeholder
  local ex_django
  ex_django=$(parse_env_file ".env" "DJANGO_SECRET_KEY" "")
  if [[ -z "$ex_django" || "$ex_django" == "dev_secret_key" ]]; then
    DJANGO_SECRET_KEY=$(gen_secret_long)
    info "Generated DJANGO_SECRET_KEY"
  else
    DJANGO_SECRET_KEY="$ex_django"
    info "Preserved existing DJANGO_SECRET_KEY"
  fi

  # CPF_INTERNAL_SERVICE_SECRET
  local ex_cpf
  ex_cpf=$(parse_env_file ".env" "CPF_INTERNAL_SERVICE_SECRET" "")
  if [[ -z "$ex_cpf" || "$ex_cpf" == "default_internal_secret_change_me" ]]; then
    CPF_INTERNAL_SERVICE_SECRET=$(gen_secret_base64)
    info "Generated CPF_INTERNAL_SERVICE_SECRET"
  else
    CPF_INTERNAL_SERVICE_SECRET="$ex_cpf"
    info "Preserved existing CPF_INTERNAL_SERVICE_SECRET"
  fi

  # OIDC RSA private key (expensive — preserve existing)
  local ex_oidc
  ex_oidc=$(parse_env_file ".env" "OIDC_RSA_PRIVATE_KEY" "")
  if [[ -z "$ex_oidc" ]]; then
    info "Generating 4096-bit RSA key for OIDC (may take a few seconds)..."
    OIDC_RSA_PRIVATE_KEY=$(openssl genrsa 4096 2>/dev/null)
    ok "RSA key generated"
  else
    OIDC_RSA_PRIVATE_KEY="$ex_oidc"
    info "Preserved existing OIDC RSA key"
  fi

  # LibreChat secrets
  local ex_ck ex_ci ex_jwt ex_jrt ex_oss ex_mmk
  ex_ck=$(parse_env_file "chat-config/.env" "CREDS_KEY" "")
  ex_ci=$(parse_env_file "chat-config/.env" "CREDS_IV" "")
  ex_jwt=$(parse_env_file "chat-config/.env" "JWT_SECRET" "")
  ex_jrt=$(parse_env_file "chat-config/.env" "JWT_REFRESH_SECRET" "")
  ex_oss=$(parse_env_file ".env" "OPENID_SESSION_SECRET" "")
  ex_mmk=$(parse_env_file "chat-config/.env" "MEILI_MASTER_KEY" "")

  CREDS_KEY=$( [[ -z "$ex_ck"  || "$ex_ck"  == "your-32-char-credentials-key-here" ]] && gen_hex 16   || echo "$ex_ck" )
  CREDS_IV=$(  [[ -z "$ex_ci"  || "$ex_ci"  == "your-16-char-iv-here"              ]] && gen_hex 8    || echo "$ex_ci" )
  JWT_SECRET=$([[ -z "$ex_jwt" || "$ex_jwt" == "your-jwt-secret-key-here"          ]] && gen_secret_base64 || echo "$ex_jwt")
  JWT_REFRESH_SECRET=$([[ -z "$ex_jrt" || "$ex_jrt" == "your-jwt-refresh-secret-here" ]] && gen_secret_base64 || echo "$ex_jrt")
  OPENID_SESSION_SECRET=$([[ -z "$ex_oss" || "$ex_oss" == "change_me_openid_session_secret" ]] && gen_secret_base64 || echo "$ex_oss")
  MEILI_MASTER_KEY=$([[ -z "$ex_mmk" || "$ex_mmk" == "masterkey" ]] && gen_secret_base64 || echo "$ex_mmk")

  ok "All secrets ready"
}

# =============================================================================
# PHASE 4: Generate Config Files
# =============================================================================
phase4_generate_configs() {
  hdr "Phase 4: Generate Config Files"
  echo ""

  mkdir -p "$REPO_ROOT/logs"

  # Determine URLs
  local web_url librechat_url oidc_iss
  if [[ "$(tolower "$USE_HTTPS")" == "y" ]]; then
    web_url="https://localhost:8443"
    librechat_url="https://localhost:3443"
    oidc_iss="https://localhost:8443/o"
  else
    web_url="http://localhost:8000"
    librechat_url="http://localhost:3080"
    oidc_iss="http://localhost:8000/o"
  fi

  # ES vars
  local es_endpoint="" es_cloud_id="" es_user="" es_password="" es_api_key=""
  case "$ES_MODE" in
    local)
      es_endpoint="http://elasticsearch:9200"
      es_user="elastic"
      es_password="$ES_PASSWORD"
      ;;
    cloud)
      es_cloud_id="$ES_CLOUD_ID"
      es_api_key="$ES_API_KEY"
      ;;
  esac

  # ── .env ─────────────────────────────────────────────────────────────────
  local env_file="$REPO_ROOT/.env"
  local overwrite_env="y"
  if [[ -f "$env_file" && "$NON_INTERACTIVE" != "true" ]]; then
    prompt_yn "overwrite_env" ".env already exists — overwrite?" "y"
  fi

  if [[ "$(tolower "$overwrite_env")" == "y" ]]; then
    cat > "$env_file" <<ENVEOF
# Generated by setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Re-run ./setup.sh to update values.

# Django
DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
DEBUG=1

# PostgreSQL (via docker compose)
DATABASE_URL=postgres://postgres:postgres@db:5432/codepathfinder

# Elasticsearch
ELASTICSEARCH_ENDPOINT=${es_endpoint}
ELASTICSEARCH_CLOUD_ID=${es_cloud_id}
ELASTICSEARCH_USER=${es_user}
ELASTICSEARCH_PASSWORD=${es_password}
ELASTICSEARCH_API_KEY=${es_api_key}
ELASTICSEARCH_INDEX=code-chunks
ELASTICSEARCH_INFERENCE_ID=.elser-2-elasticsearch

# Google OAuth (optional)
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}

# Internal service authentication (shared with LibreChat via docker-compose)
CPF_INTERNAL_SERVICE_SECRET=${CPF_INTERNAL_SERVICE_SECRET}

# LibreChat integration
LIBRECHAT_EXTERNAL_URL=${librechat_url}

# OIDC — CodePathfinder is the identity provider for LibreChat SSO
# OPENID_CLIENT_ID and OPENID_CLIENT_SECRET are populated in Phase 7
OPENID_CLIENT_ID=${OPENID_CLIENT_ID}
OPENID_CLIENT_SECRET=${OPENID_CLIENT_SECRET}
OPENID_SESSION_SECRET=${OPENID_SESSION_SECRET}
OIDC_ISS_ENDPOINT=${oidc_iss}

# OIDC RSA private key (used to sign ID tokens issued to LibreChat)
OIDC_RSA_PRIVATE_KEY=${OIDC_RSA_PRIVATE_KEY}

# GitHub (optional — for indexing private repos)
GITHUB_TOKEN=${GITHUB_TOKEN}

# OTel internal instrumentation (local dev)
OTEL_ENABLED=true
OTEL_SERVICE_NAME=codepathfinder-web
CPF_PROJECT_ID=12

# Kibana service account token (local dev default)
KIBANA_SERVICE_ACCOUNT_TOKEN=AAEAAWVsYXN0aWMva2liYW5hL2tpYmFuYS10b2tlbjo3U1p6Mm0ybFJNQ1hYSWxpakkxcUln

# Anonymous usage telemetry — set to false to opt out (see docs/TELEMETRY.md)
INSTALLATION_ID=${INSTALLATION_ID}
TELEMETRY_ENABLED=true
ENVEOF
    ok "Generated .env"
  else
    info "Kept existing .env"
  fi

  # ── chat-config/.env ──────────────────────────────────────────────────────
  local chat_env="$REPO_ROOT/chat-config/.env"
  local overwrite_chat="y"
  if [[ -f "$chat_env" && "$NON_INTERACTIVE" != "true" ]]; then
    prompt_yn "overwrite_chat" "chat-config/.env already exists — overwrite?" "y"
  fi

  if [[ "$(tolower "$overwrite_chat")" == "y" ]]; then
    cat > "$chat_env" <<CHATEOF
# Generated by setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")

#==================================================#
#                  LibreChat Config                 #
#==================================================#

# Security Keys (auto-generated by setup.sh)
CREDS_KEY=${CREDS_KEY}
CREDS_IV=${CREDS_IV}
JWT_SECRET=${JWT_SECRET}
JWT_REFRESH_SECRET=${JWT_REFRESH_SECRET}

# MongoDB (LibreChat's database)
MONGO_URI=mongodb://mongodb:27017/librechat

# MeiliSearch (LibreChat's search)
MEILI_HOST=http://meilisearch:7700
MEILI_MASTER_KEY=${MEILI_MASTER_KEY}

#==================================================#
#                   LLM API Keys                    #
#==================================================#
OPENAI_API_KEY=${OPENAI_API_KEY}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
AZURE_API_KEY=${AZURE_API_KEY}
GEMINI_API_KEY=${GEMINI_API_KEY}
GROQ_API_KEY=
TOGETHER_API_KEY=
OPENROUTER_API_KEY=
BEDROCK_AWS_ACCESS_KEY_ID=${BEDROCK_ACCESS_KEY}
BEDROCK_AWS_SECRET_ACCESS_KEY=${BEDROCK_SECRET_KEY}
BEDROCK_AWS_DEFAULT_REGION=${BEDROCK_REGION}

#==================================================#
#               Optional Settings                   #
#==================================================#
DEBUG_CONSOLE=false
ALLOW_REGISTRATION=true
ALLOW_SOCIAL_LOGIN=false
CHATEOF
    ok "Generated chat-config/.env"
  else
    info "Kept existing chat-config/.env"
  fi

  # ── indexer/.env ──────────────────────────────────────────────────────────
  if [[ "$ES_MODE" != "skip" ]]; then
    local indexer_env="$REPO_ROOT/indexer/.env"
    local overwrite_idx="y"
    if [[ -f "$indexer_env" && "$NON_INTERACTIVE" != "true" ]]; then
      prompt_yn "overwrite_idx" "indexer/.env already exists — overwrite?" "y"
    fi

    if [[ "$(tolower "$overwrite_idx")" == "y" ]]; then
      cat > "$indexer_env" <<IDXEOF
# Generated by setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
ELASTICSEARCH_ENDPOINT=${es_endpoint}
ELASTICSEARCH_CLOUD_ID=${es_cloud_id}
ELASTICSEARCH_USER=${es_user}
ELASTICSEARCH_PASSWORD=${es_password}
ELASTICSEARCH_API_KEY=${es_api_key}
ELASTICSEARCH_INDEX=code-chunks
ELASTICSEARCH_INFERENCE_ID=.elser-2-elasticsearch
GITHUB_TOKEN=${GITHUB_TOKEN}
IDXEOF
      ok "Generated indexer/.env"
    else
      info "Kept existing indexer/.env"
    fi
  fi

  # ── Azure OpenAI: append to librechat.yaml if needed ─────────────────────
  if echo "$LLM_SELECTION" | grep -qE "(^|,) *3( *,|$)"; then
    local librechat_yaml="$REPO_ROOT/chat-config/librechat.yaml"
    if [[ -f "$librechat_yaml" ]] && ! grep -q "azureOpenAI" "$librechat_yaml" 2>/dev/null; then
      cat >> "$librechat_yaml" <<YAMLEOF

# Azure OpenAI — added by setup.sh
endpoints:
  azureOpenAI:
    apiKey: "\${AZURE_API_KEY}"
    instanceName: "${AZURE_INSTANCE_NAME}"
    version: "${AZURE_API_VERSION}"
    models:
      default: ["gpt-4o", "gpt-4o-mini"]
YAMLEOF
      ok "Appended Azure OpenAI config to chat-config/librechat.yaml"
    else
      info "Azure OpenAI already configured or librechat.yaml not found — skipping"
    fi
  fi

  ok "Config files ready"
}

# =============================================================================
# PHASE 5: Infrastructure Setup
# =============================================================================
phase5_infrastructure() {
  hdr "Phase 5: Infrastructure Setup"
  echo ""

  # Git submodules
  info "Updating git submodules..."
  git submodule update --init --recursive >> "$REPO_ROOT/logs/setup.log" 2>&1
  ok "Git submodules updated"

  # Docker network
  if docker network inspect cpf-librechat >/dev/null 2>&1; then
    info "Docker network cpf-librechat already exists"
  else
    docker network create cpf-librechat >/dev/null
    ok "Created Docker network cpf-librechat"
  fi

  # Docker volumes
  for vol in pathfinder_postgres_data pathfinder_elasticsearch_data; do
    if docker volume inspect "$vol" >/dev/null 2>&1; then
      info "Volume $vol already exists"
    else
      docker volume create "$vol" >/dev/null
      ok "Created volume $vol"
    fi
  done

  # mkcert SSL certs
  if [[ "$(tolower "$USE_HTTPS")" == "y" && "$MKCERT_AVAILABLE" == "true" ]]; then
    local cert_dir="$REPO_ROOT/nginx/certs"
    mkdir -p "$cert_dir"
    if [[ -f "$cert_dir/localhost.pem" && -f "$cert_dir/localhost-key.pem" ]]; then
      info "SSL certificates already exist — skipping mkcert"
    else
      info "Generating SSL certificates with mkcert..."
      (cd "$cert_dir" && mkcert -cert-file localhost.pem -key-file localhost-key.pem localhost 127.0.0.1 ::1) >> "$REPO_ROOT/logs/setup.log" 2>&1
      local ca_root
      ca_root=$(mkcert -CAROOT 2>/dev/null || true)
      if [[ -n "$ca_root" && -f "$ca_root/rootCA.pem" ]]; then
        cp "$ca_root/rootCA.pem" "$cert_dir/rootCA.pem"
      fi
      ok "SSL certificates generated in nginx/certs/"
    fi
  fi
}

# =============================================================================
# PHASE 6: Build & Start Services
# =============================================================================
phase6_build_and_start() {
  if [[ "$SKIP_START" == "true" ]]; then
    info "Skipping Phase 6 (--skip-start)"
    return
  fi

  hdr "Phase 6: Build & Start Services"
  echo ""
  info "Verbose output → logs/setup.log"
  echo ""

  # Services to exclude when ES is skipped
  local es_exclude=()
  if [[ "$ES_MODE" == "skip" ]]; then
    es_exclude=(--scale elasticsearch=0 --scale kibana=0 --scale indexer=0)
  fi

  if [[ "$SKIP_BUILD" == "false" ]]; then
    spinner_start "Building Docker images (this may take several minutes)..."
    docker compose build "${es_exclude[@]:-}" >> "$REPO_ROOT/logs/setup.log" 2>&1 || {
      spinner_stop
      err "docker compose build failed — see logs/setup.log"
      exit 1
    }
    spinner_stop
    ok "Docker images built"
  fi

  spinner_start "Starting services..."
  docker compose up -d "${es_exclude[@]:-}" >> "$REPO_ROOT/logs/setup.log" 2>&1 || {
    spinner_stop
    err "docker compose up failed — see logs/setup.log"
    exit 1
  }
  spinner_stop
  ok "Services started"

  # Wait for Django web to be healthy
  info "Waiting for Django web service..."
  local timeout=120
  local elapsed=0
  printf "  "
  while [[ $elapsed -lt $timeout ]]; do
    if curl -sf "http://localhost:8000/health/" >/dev/null 2>&1; then
      echo ""
      ok "Web service is responding"
      return
    fi
    printf "."
    sleep 5
    elapsed=$((elapsed + 5))
  done
  echo ""
  warn "Web service health check timed out — services may still be starting"
  info "Check: docker compose logs web"
}

# =============================================================================
# PHASE 7: Django First-Run Setup
# =============================================================================
phase7_django_setup() {
  if [[ "$SKIP_START" == "true" ]]; then
    info "Skipping Phase 7 (--skip-start)"
    return
  fi

  hdr "Phase 7: Django First-Run Setup"
  echo ""

  # 0. Poll for PostgreSQL readiness
  info "Waiting for PostgreSQL..."
  local pg_timeout=60
  local pg_elapsed=0
  printf "  "
  while [[ $pg_elapsed -lt $pg_timeout ]]; do
    if docker compose exec -T db pg_isready -U postgres -d codepathfinder >/dev/null 2>&1; then
      echo ""
      ok "PostgreSQL is ready"
      break
    fi
    printf "."
    sleep 2
    pg_elapsed=$((pg_elapsed + 2))
  done
  echo ""

  if [[ $pg_elapsed -ge $pg_timeout ]]; then
    err "PostgreSQL did not become ready within ${pg_timeout}s"
    exit 1
  fi

  # 1. Migrations
  info "Running database migrations..."
  docker compose exec -T web python manage.py migrate
  ok "Migrations complete"
  echo ""

  # 2. Superuser
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    warn "Non-interactive mode: skipping superuser creation"
    info "Run manually: docker compose exec web python manage.py createsuperuser"
  else
    echo -e "  ${BOLD}Create Django superuser${NC} (your CodePathfinder admin account)"
    echo ""
    docker compose exec web python manage.py createsuperuser || true
  fi
  echo ""

  # 3. LibreChat OIDC application
  info "Creating LibreChat OIDC application..."
  local oidc_output
  oidc_output=$(docker compose exec -T web python manage.py create_librechat_oidc_app 2>&1)
  echo "$oidc_output"
  echo ""

  # Parse credentials from command output
  OPENID_CLIENT_ID=$(echo "$oidc_output"   | grep "OPENID_CLIENT_ID"     | awk '{print $NF}')
  OPENID_CLIENT_SECRET=$(echo "$oidc_output" | grep "OPENID_CLIENT_SECRET" | awk '{print $NF}')

  if [[ -n "$OPENID_CLIENT_ID" && -n "$OPENID_CLIENT_SECRET" ]]; then
    ok "OIDC credentials obtained — updating .env"

    # Inject into .env
    for kv_pair in "OPENID_CLIENT_ID=${OPENID_CLIENT_ID}" "OPENID_CLIENT_SECRET=${OPENID_CLIENT_SECRET}"; do
      local key="${kv_pair%%=*}"
      local val="${kv_pair#*=}"
      if grep -q "^${key}=" "$REPO_ROOT/.env" 2>/dev/null; then
        sed_inplace "s|^${key}=.*|${key}=${val}|" "$REPO_ROOT/.env"
      else
        echo "${key}=${val}" >> "$REPO_ROOT/.env"
      fi
    done

    # Also append to chat-config/.env for reference (docker-compose picks up from env block)
    {
      echo ""
      echo "# OIDC credentials (auto-populated by setup.sh Phase 7)"
      echo "OPENID_CLIENT_ID=${OPENID_CLIENT_ID}"
      echo "OPENID_CLIENT_SECRET=${OPENID_CLIENT_SECRET}"
    } >> "$REPO_ROOT/chat-config/.env"

    # 4. Restart LibreChat with OIDC credentials
    info "Restarting LibreChat to pick up OIDC credentials..."
    docker compose restart librechat >> "$REPO_ROOT/logs/setup.log" 2>&1
    ok "LibreChat restarted with OIDC config"
  else
    warn "Could not parse OIDC credentials — LibreChat SSO not configured automatically"
    info "Re-run: docker compose exec web python manage.py create_librechat_oidc_app"
    info "Then manually update OPENID_CLIENT_ID/SECRET in .env and restart LibreChat"
  fi
}

# =============================================================================
# PHASE 8: Health Verification
# =============================================================================
phase8_health_check() {
  if [[ "$SKIP_START" == "true" ]]; then
    info "Skipping Phase 8 (--skip-start)"
    return
  fi

  hdr "Phase 8: Health Verification"
  echo ""

  local web_url librechat_url
  if [[ "$(tolower "$USE_HTTPS")" == "y" ]]; then
    web_url="https://localhost:8443"
    librechat_url="https://localhost:3443"
  else
    web_url="http://localhost:8000"
    librechat_url="http://localhost:3080"
  fi

  local curl_flags=""
  [[ "$(tolower "$USE_HTTPS")" == "y" ]] && curl_flags="-k"

  check_svc() {
    local name="$1" url="$2" flags="${3:-}"
    # shellcheck disable=SC2086
    if curl -sf --max-time 5 $flags "$url" >/dev/null 2>&1; then
      printf "  │ %-22s │ ${GREEN}%-8s${NC} │\n" "$name" "UP"
    else
      printf "  │ %-22s │ ${RED}%-8s${NC} │\n" "$name" "DOWN"
    fi
  }

  echo "  ┌──────────────────────────┬──────────────┐"
  printf "  │ %-24s │ %-12s │\n" "Service" "Status"
  echo "  ├──────────────────────────┼──────────────┤"
  check_svc "Django Web"         "${web_url}/health/"          "$curl_flags"
  check_svc "LibreChat"          "${librechat_url}"            "$curl_flags"
  check_svc "PostgreSQL (port)"  "http://localhost:5432"       ""
  if [[ "$ES_MODE" == "local" ]]; then
    check_svc "Elasticsearch"    "http://localhost:9200"       ""
    check_svc "Kibana"           "http://localhost:5601"       ""
  fi
  check_svc "MongoDB (port)"     "http://localhost:27017"      ""
  check_svc "Meilisearch"        "http://localhost:7700/health" ""
  echo "  └──────────────────────────┴──────────────┘"
  echo ""
  info "PostgreSQL and MongoDB may show DOWN via HTTP — they are not HTTP services"
}

# =============================================================================
# PHASE 9: Summary & Next Steps
# =============================================================================
phase9_summary() {
  hdr "Phase 9: Summary & Next Steps"
  echo ""

  local web_url librechat_url
  if [[ "$(tolower "$USE_HTTPS")" == "y" ]]; then
    web_url="https://localhost:8443"
    librechat_url="https://localhost:3443"
  else
    web_url="http://localhost:8000"
    librechat_url="http://localhost:3080"
  fi

  echo -e "  ${BOLD}Service URLs${NC}"
  echo "  ┌──────────────────────┬────────────────────────────────┐"
  printf "  │ %-20s │ %-30s │\n" "CodePathfinder"    "${web_url}"
  printf "  │ %-20s │ %-30s │\n" "Django Admin"      "${web_url}/admin/"
  printf "  │ %-20s │ %-30s │\n" "LibreChat"         "${librechat_url}"
  if [[ "$ES_MODE" == "local" ]]; then
    printf "  │ %-20s │ %-30s │\n" "Kibana"            "http://localhost:5601"
    printf "  │ %-20s │ %-30s │\n" "Elasticsearch"     "http://localhost:9200"
  fi
  echo "  └──────────────────────┴────────────────────────────────┘"
  echo ""

  echo -e "  ${BOLD}LLM Providers${NC}"
  if [[ -z "$LLM_SELECTION" ]]; then
    warn "None configured — add keys to chat-config/.env and restart LibreChat"
  else
    IFS=',' read -ra nums <<< "$LLM_SELECTION"
    for n in "${nums[@]}"; do
      n="${n// /}"
      case "$n" in
        1) ok "OpenAI" ;;
        2) ok "Anthropic" ;;
        3) ok "Azure OpenAI" ;;
        4) ok "Google Gemini" ;;
        5) ok "AWS Bedrock" ;;
      esac
    done
  fi
  echo ""

  echo -e "  ${BOLD}Next Steps${NC}"
  echo ""
  if [[ "$SKIP_START" == "true" ]]; then
    echo "  1. Start services:       docker compose up -d"
    echo "  2. Run migrations:       docker compose exec web python manage.py migrate"
    echo "  3. Create superuser:     docker compose exec web python manage.py createsuperuser"
    echo "  4. Create OIDC app:      docker compose exec web python manage.py create_librechat_oidc_app"
    echo "  5. Update .env OIDC IDs and restart LibreChat: docker compose restart librechat"
    echo ""
  else
    echo "  All services are running!"
    echo ""
  fi

  echo "  Index a repository:   ${web_url}/projects/ → Create Project → Add GitHub Repo"
  echo ""

  if [[ -z "${OPENAI_API_KEY:-}" && -z "${ANTHROPIC_API_KEY:-}" && -z "${AZURE_API_KEY:-}" ]]; then
    echo "  Add LLM API keys:"
    echo "    1. Edit chat-config/.env"
    echo "    2. docker compose restart librechat"
    echo ""
  fi

  echo "  Documentation:   ${web_url}/docs/"
  echo "  Setup log:       ${REPO_ROOT}/logs/setup.log"
  echo ""

  # ── Send install telemetry (anonymous, opt-out with TELEMETRY_ENABLED=false) ──
  local telem_enabled
  telem_enabled=$(parse_env_file "$REPO_ROOT/.env" "TELEMETRY_ENABLED" "true")
  if [[ "$(tolower "$telem_enabled")" == "true" && "$SKIP_START" == "false" ]]; then
    local llm_count=0
    if [[ -n "$LLM_SELECTION" ]]; then
      IFS=',' read -ra _p <<< "$LLM_SELECTION"
      llm_count="${#_p[@]}"
    fi
    local os_type
    os_type=$(uname -s | tr '[:upper:]' '[:lower:]')
    local telem_payload
    telem_payload=$(printf '{"event_type":"install","installation_id":"%s","version":"oss","os_type":"%s","es_mode":"%s","llm_providers_count":%d,"timestamp":"%s"}' \
      "$INSTALLATION_ID" "$os_type" "$ES_MODE" "$llm_count" \
      "$(date -u +"%Y-%m-%dT%H:%M:%SZ")")
    if command -v curl >/dev/null 2>&1; then
      curl -sf --max-time 5 -X POST \
        -H "Content-Type: application/json" \
        -d "$telem_payload" \
        "https://codepathfinder.com/telemetry/event" >/dev/null 2>&1 || true
    fi
    info "Anonymous telemetry enabled. Set TELEMETRY_ENABLED=false in .env to opt out (docs/TELEMETRY.md)"
  fi

  echo -e "  ${GREEN}${BOLD}Setup complete!${NC}"
  echo ""
}

# =============================================================================
# MAIN
# =============================================================================
main() {
  echo ""
  echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║    CodePathfinder Interactive Setup      ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
  echo ""

  [[ "$SKIP_START"       == "true" ]] && info "Mode: config-only (--skip-start)"
  [[ "$NON_INTERACTIVE"  == "true" ]] && info "Mode: non-interactive"
  [[ "$SKIP_BUILD"       == "true" ]] && info "Flag: --skip-build"
  echo ""

  phase1_prerequisites
  phase2_interactive_config
  phase3_generate_secrets
  phase4_generate_configs
  phase5_infrastructure
  phase6_build_and_start
  phase7_django_setup
  phase8_health_check
  phase9_summary
}

main "$@"
