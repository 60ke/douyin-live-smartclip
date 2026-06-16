# Staging Docker 部署流程

本文记录 `douyin-live-smartclip` 在 staging 服务器上的 Docker 部署方式。

## 服务器信息

- 后端服务器：`192.168.2.191`
- 登录用户：`qc`
- Docker 命令：需要 `sudo`
- API 端口：宿主机 `9889` -> 容器 `8000`
- 项目目录：`/home/qc/lsk/douyin-live-smartclip`
- Compose 项目：`douyin-live-smartclip`
- 服务：
  - `liveclip-mysql`：MySQL 8.0
  - `liveclip-server`：FastAPI + 内置 worker

## 发布代码

如果本地访问 GitHub 不稳定，可以临时使用代理推送：

```bash
export https_proxy=http://127.0.0.1:7890
export http_proxy=http://127.0.0.1:7890
export all_proxy=socks5://127.0.0.1:7890

git push origin master
```

推送完成后可以按需取消代理：

```bash
unset https_proxy http_proxy all_proxy
```

## 常规部署

在服务器执行：

```bash
ssh qc@192.168.2.191
cd /home/qc/lsk/douyin-live-smartclip

git fetch origin master
git pull --ff-only origin master

sudo docker compose build liveclip
sudo docker compose up -d liveclip
```

首次部署或 MySQL 不存在时，直接启动全部服务：

```bash
sudo docker compose up -d --build
```

不要使用 `docker compose down -v`，否则会删除 MySQL 命名卷数据。

## 配置文件

`.env` 至少需要包含：

```ini
LIVECLIP_CONFIG=configs/app.toml
MYSQL_ROOT_PASSWORD=liveclip_root_password
MYSQL_DATABASE=liveclip
MYSQL_USER=liveclip
MYSQL_PASSWORD=liveclip_password
LLM_API_KEY=sk-xxxxx
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash
LLM_BASE_URL=https://api.siliconflow.cn/v1/chat/completions
DOUYIN_COOKIE=
```

`configs/app.toml` 中数据库连接应指向 compose 内的 MySQL 服务：

```toml
[database]
url = "mysql+asyncmy://liveclip:liveclip_password@mysql:3306/liveclip?charset=utf8mb4"

[worker]
auto_start_with_api = true

[funasr]
device = "auto"
```

如果 `.env` 中修改了 `MYSQL_USER` 或 `MYSQL_PASSWORD`，需要同步修改 `configs/app.toml` 的连接串。

## 数据保留

当前持久化位置：

```text
douyin-live-smartclip_mysql_data  # Docker volume，MySQL 8.0 数据
./data                            # 录制视频、字幕、切片结果等应用文件
./cache                           # FunASR / Hugging Face / ModelScope 缓存
./logs                            # 应用日志
```

升级前建议备份：

```bash
cd /home/qc/lsk/douyin-live-smartclip
TS=$(date +%Y%m%d_%H%M%S)
BK=/home/qc/liveclip-backups/$TS
mkdir -p "$BK"

cp -a .env docker-compose.yml configs/app.toml "$BK"/
tar -czf "$BK/data.tgz" data
sudo docker inspect liveclip-server > "$BK/liveclip-server.inspect.json"
sudo docker compose exec -T mysql mysqldump -uliveclip -pliveclip_password liveclip > "$BK/liveclip.sql"
```

## 健康检查

```bash
curl http://127.0.0.1:9889/health
curl 'http://127.0.0.1:9889/api/v1/live-rooms/?offset=0&limit=5'
sudo docker compose ps
sudo docker compose logs --tail 120 liveclip
```

从本机也可以验证：

```bash
curl http://192.168.2.191:9889/health
```

## CUDA / GPU 部署

### 当前状态

服务器宿主机能看到 NVIDIA GPU，但普通 `docker-compose.yml` 启动的 `liveclip-server` 容器不会自动获得 GPU。

当前验证结果：

```text
宿主机：nvidia-smi 能看到 NVIDIA RTX 5880 Ada Generation
容器内：torch.cuda.is_available() == False
容器内：torch.cuda.device_count() == 0
```

这说明镜像内 PyTorch/CUDA 依赖已经安装，但当前容器没有暴露宿主机 GPU 设备。要让 FunASR 使用 CUDA，必须使用 GPU compose override 重新创建 `liveclip` 容器。

### 宿主机前置检查

```bash
nvidia-smi
nvidia-ctk --version || nvidia-container-toolkit --version
sudo docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

如果 `docker run --gpus all ... nvidia-smi` 失败，需要先配置 NVIDIA Container Toolkit，例如：

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

重启 Docker 后再次执行 `docker run --rm --gpus all ... nvidia-smi` 验证。

### GPU 启动命令

项目提供 `docker-compose.gpu.yml`：

```yaml
services:
  liveclip:
    gpus: all
    environment:
      NVIDIA_VISIBLE_DEVICES: ${NVIDIA_VISIBLE_DEVICES:-all}
      NVIDIA_DRIVER_CAPABILITIES: ${NVIDIA_DRIVER_CAPABILITIES:-compute,utility,video}
```

使用 GPU 方式启动：

```bash
cd /home/qc/lsk/douyin-live-smartclip
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build liveclip
```

验证容器是否拿到 GPU：

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T liveclip sh -lc '
nvidia-smi -L
/app/.venv/bin/python - <<PY
import torch
print("torch_cuda_available=", torch.cuda.is_available())
print("torch_device_count=", torch.cuda.device_count())
PY
'
```

期望结果：

```text
torch_cuda_available= True
torch_device_count= 1  # 或更多
```

`configs/app.toml` 中 `[funasr].device = "auto"` 时，只要容器内 `torch.cuda.is_available()` 为 true，FunASR 会自动选择 `cuda`；也可以显式配置为：

```toml
[funasr]
device = "cuda"
```

## 镜像源

Dockerfile 已做国内源适配：

- apt：清华 Debian 源
- pip / uv：清华 PyPI 源
- Hugging Face：`https://hf-mirror.com`

基础镜像 `python:3.11-slim` 的拉取速度取决于服务器 Docker daemon 的 registry mirror 配置。
