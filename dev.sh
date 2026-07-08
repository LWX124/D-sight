#!/usr/bin/env bash
# D-sight 开发调试一键启动脚本
#
#   ./dev.sh          启动全部：docker(pg+redis) → 迁移 → 种子 skill → 后端 → 前端
#   ./dev.sh down     停止 docker 服务（保留数据卷）
#   ./dev.sh fresh    重置数据库（docker down -v 清空）后全新启动
#   ./dev.sh --no-seed 跳过 skill 种子（库已种过时更快）
#
# 端口集中在下方声明，均可用环境变量覆盖，例如：
#   BACKEND_PORT=8100 FRONTEND_PORT=5200 ./dev.sh
#
# 部署注意：这些是"开发端口"，postgres/redis 已从标准端口(5432/6379)
# 重映射到 5434/6381 以避开本机其它服务。生产部署请按目标机实际情况
# 用环境变量重设，并确保 docker-compose 映射、backend/.env 的 DATABASE_URL
# / REDIS_URL、前端代理 target 三处端口一致。
set -euo pipefail

# ---- 端口（可 env 覆盖）----
# 后端/前端默认用 8010/5183，避开本机另一项目占用的 8000/5173。
# postgres/redis 已重映射到 5434/6381 避开标准端口 5432/6379。
POSTGRES_PORT="${POSTGRES_PORT:-5434}"
REDIS_PORT="${REDIS_PORT:-6381}"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5183}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT/docker-compose.dev.yml"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

# ---- 小工具 ----
c_green='\033[0;32m'; c_yellow='\033[0;33m'; c_red='\033[0;31m'; c_dim='\033[2m'; c_off='\033[0m'
log()  { printf "${c_green}▶ %s${c_off}\n" "$*"; }
warn() { printf "${c_yellow}⚠ %s${c_off}\n" "$*"; }
die()  { printf "${c_red}✗ %s${c_off}\n" "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "缺少依赖：$1（请先安装）"; }

# docker compose (v2) 优先，回退 docker-compose (v1)
compose() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@";
  else docker-compose "$@"; fi
}

port_owner() {  # 打印占用某端口的进程简述（空=未占用）
  # 末尾 || true：端口空闲时 lsof 退出码为 1，配合 set -o pipefail 会误触发 set -e
  # 让整支脚本静默秒退，这里吞掉使其恒返回 0。
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" (pid "$2")"}' || true
}

# ---- 子命令：停止 / 重置 ----
if [[ "${1:-}" == "down" ]]; then
  log "停止 docker 服务（保留数据）"; compose -f "$COMPOSE_FILE" down; exit 0
fi
FRESH=0; NO_SEED=0
for arg in "$@"; do
  case "$arg" in
    fresh)     FRESH=1 ;;
    --no-seed) NO_SEED=1 ;;
    *) die "未知参数：$arg" ;;
  esac
done

# 开跑即打横幅（若这行都看不到，说明你的输出被缓冲/不是真终端，见文末提示）
printf "${c_green}==== D-sight dev 启动中（后端 %s / 前端 %s）====${c_off}\n" "$BACKEND_PORT" "$FRONTEND_PORT"

# ---- 依赖检查 ----
need docker; need uv; need node; need npm
[[ -f "$BACKEND/.env" ]] || die "缺少 $BACKEND/.env（数据库连接与密钥）。参考 backend/.env.example 创建。"
# Docker Desktop 的真实 socket 存在就强制用它，盖掉从 shell 继承来的可能有问题的
# DOCKER_HOST/DOCKER_CONTEXT（这是 docker info 无限挂起的常见根因）。
if [[ -S "$HOME/.docker/run/docker.sock" ]]; then
  export DOCKER_HOST="unix://$HOME/.docker/run/docker.sock"
  unset DOCKER_CONTEXT 2>/dev/null || true
fi

# docker 守护进程必须活着，否则 compose 会一直卡在连接。
# 关键：给 docker info 加硬超时(6s)——某些环境下 socket 错配会让它无限挂起。
with_timeout() {  # 用法: with_timeout <秒> <命令...>；超时返回 124
  local secs="$1"; shift
  "$@" & local cpid=$!
  ( sleep "$secs"; kill -9 "$cpid" 2>/dev/null ) & local wpid=$!
  local rc=0; wait "$cpid" 2>/dev/null || rc=$?
  kill "$wpid" 2>/dev/null; wait "$wpid" 2>/dev/null || true
  return "$rc"
}
log "检查 docker 守护进程（最多 6s）…"
if ! with_timeout 6 docker info >/dev/null 2>&1; then
  die "docker 无法连通（info 超时/失败）。排查：
     1) 确认 Docker Desktop 正在运行（鲸鱼图标稳定）；
     2) 在本终端跑 'docker info' 看是否也卡——若卡：退出并重开 Docker Desktop；
     3) 若交互式能跑而本脚本不行，多半是 socket 配置只在 .zshrc 里。
        解法：把 'export DOCKER_HOST=unix://\$HOME/.docker/run/docker.sock' 加到脚本或环境，
        或运行 'docker context use desktop-linux' 后重试。"
fi

# ---- 应用端口预检（docker 端口由 compose 兜底报错，这里只查前后端）----
for pair in "backend:$BACKEND_PORT" "frontend:$FRONTEND_PORT"; do
  name="${pair%%:*}"; p="${pair##*:}"; owner="$(port_owner "$p")"
  if [[ -n "$owner" ]]; then
    upper="$(printf '%s' "$name" | tr '[:lower:]' '[:upper:]')"
    die "${name} 端口 ${p} 已被占用：${owner} 。释放它：kill <pid>，或换端口：${upper}_PORT=<新端口> ./dev.sh"
  fi
done
for pair in "postgres:$POSTGRES_PORT" "redis:$REDIS_PORT"; do
  name="${pair%%:*}"; p="${pair##*:}"; owner="$(port_owner "$p")"
  # docker 自己占着这两个端口是正常的；仅当被非 docker 进程占用时提前警示
  if [[ -n "$owner" && "$owner" != com.docker* && "$owner" != docker* ]]; then
    warn "$name 端口 $p 被 $owner 占用（若非本项目 docker，compose 将起不来）"
  fi
done

# ---- 启动 docker（postgres + redis）----
[[ -f "$COMPOSE_FILE" ]] || die "找不到 $COMPOSE_FILE"
if [[ $FRESH -eq 1 ]]; then
  warn "fresh：清空数据库卷"; compose -f "$COMPOSE_FILE" down -v || true
fi
log "启动 docker：postgres:$POSTGRES_PORT redis:$REDIS_PORT"
POSTGRES_PORT="$POSTGRES_PORT" REDIS_PORT="$REDIS_PORT" \
  compose -f "$COMPOSE_FILE" up -d

# ---- 等 postgres 就绪 ----
log "等待 postgres 就绪 …"
for i in $(seq 1 60); do
  if compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U dsight -d dsight >/dev/null 2>&1; then
    break
  fi
  [[ $i -eq 60 ]] && die "postgres 60s 内未就绪"; sleep 1
done
log "postgres 就绪"

# ---- 后端：迁移 + 种子 ----
log "数据库迁移（alembic upgrade head）"
( cd "$BACKEND" && uv run alembic upgrade head )
if [[ $NO_SEED -eq 0 ]]; then
  log "种子 skill（幂等，含存量用户补装）"
  ( cd "$BACKEND" && uv run python -m scripts.seed_skills ) || warn "种子失败（不阻断启动）"
  ( cd "$BACKEND" && uv run python -m scripts.seed_news ) || warn "news 种子失败（不阻断启动）"
fi

# ---- 启动前后端，Ctrl+C 一起清理 ----
PIDS=()
cleanup() {
  printf "\n"; log "关闭前后端 …"
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  printf "${c_dim}docker 仍在运行（数据保留）。停止：./dev.sh down${c_off}\n"
}
trap cleanup INT TERM EXIT

# 打印当前 LLM/embedding 模式，便于调试时心里有数
mode="$(grep -E '^(FAKE_LLM|EMBEDDING_BACKEND|NEWS_BACKEND)=' "$BACKEND/.env" 2>/dev/null | tr '\n' ' ' || true)"
[[ -n "$mode" ]] && printf "${c_dim}模式：%s${c_off}\n" "$mode"

log "启动后端  http://localhost:$BACKEND_PORT"
( cd "$BACKEND" && PYTHONUNBUFFERED=1 exec uv run uvicorn app.main:create_app --factory --reload --port "$BACKEND_PORT" ) &
PIDS+=($!)

log "安装前端依赖（如缺）"
[[ -d "$FRONTEND/node_modules" ]] || ( cd "$FRONTEND" && npm install )

log "启动前端  http://localhost:${FRONTEND_PORT}   （/api 代理至后端 ${BACKEND_PORT}）"
# 把 BACKEND_PORT 传给 vite，使其 /api 代理 target 跟随后端端口（见 vite.config.ts）
( cd "$FRONTEND" && BACKEND_PORT="$BACKEND_PORT" exec npm run dev -- --port "$FRONTEND_PORT" --strictPort ) &
PIDS+=($!)

printf "\n${c_green}✔ 全部启动。前端 http://localhost:%s ，后端 http://localhost:%s${c_off}\n" "$FRONTEND_PORT" "$BACKEND_PORT"
printf "${c_dim}Ctrl+C 停止前后端；docker 保留。${c_off}\n\n"
wait
