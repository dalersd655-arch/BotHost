import io, os, shutil, zipfile
from pathlib import Path
import docker
from docker.errors import NotFound, ImageNotFound
from docker.types import LogConfig
from . import config as C

_client = None
def client():
    global _client
    if _client is None: _client = docker.from_env()
    return _client

DOCKERFILE = """FROM python:3.12-slim
RUN useradd -m -u 10001 bot
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chown -R bot /app
USER bot
CMD ["python", "-u", "main.py"]
"""

def cname(bot_id): return f"tgbot-{bot_id}"
def tag(bot_id): return f"tgbot-{bot_id}:latest"
def bot_dir(bot_id): return Path(C.DATA_DIR) / "bots" / str(bot_id)

def ensure_network():
    c = client()
    try: c.networks.get(C.BOT_NETWORK)
    except NotFound:
        c.networks.create(C.BOT_NETWORK, driver="bridge",
                          options={"com.docker.network.bridge.enable_icc": "false"})

def safe_extract(data: bytes, dest: Path):
    """Распаковка zip с защитой от path traversal, симлинков и zip-бомб."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > C.MAX_FILES: raise ValueError("Слишком много файлов в архиве")
        if sum(i.file_size for i in infos) > C.MAX_UNPACKED: raise ValueError("Архив слишком большой после распаковки")
        for i in infos:
            target = (root / i.filename).resolve()
            if target != root and not str(target).startswith(str(root) + os.sep):
                raise ValueError("Недопустимый путь в архиве")
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Симлинки в архиве запрещены")
        z.extractall(root)
    # если всё лежит в одной папке — поднять на уровень выше
    items = [p for p in root.iterdir() if p.name != "__MACOSX"]
    if len(items) == 1 and items[0].is_dir():
        inner = items[0]
        for p in inner.iterdir(): shutil.move(str(p), str(root / p.name))
        inner.rmdir()
    if not (root / "main.py").exists():
        raise ValueError("В проекте нет main.py в корне")
    if not (root / "requirements.txt").exists():
        (root / "requirements.txt").write_text("")
    (root / "Dockerfile").write_text(DOCKERFILE)   # свой Dockerfile пользователя игнорируем
    (root / ".dockerignore").write_text(".git\n__pycache__\n*.pyc\n")

def build_image(bot_id):
    client().images.build(path=str(bot_dir(bot_id)), tag=tag(bot_id), rm=True, forcerm=True, timeout=600)

def run(bot_id, user_id, token, mem_mb, cpu):
    ensure_network()
    remove_container(bot_id)
    client().containers.run(
        tag(bot_id), name=cname(bot_id), detach=True,
        environment={"BOT_TOKEN": token},
        mem_limit=f"{mem_mb}m", memswap_limit=f"{mem_mb}m",
        nano_cpus=int(cpu * 1e9), pids_limit=64,
        read_only=True, tmpfs={"/tmp": "size=32m,noexec"},
        cap_drop=["ALL"], security_opt=["no-new-privileges"],
        network=C.BOT_NETWORK,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 10},
        labels={"tgbot": "1", "owner": str(user_id)},
        log_config=LogConfig(type="json-file", config={"max-size": "1m", "max-file": "2"}),
    )

def _get(bot_id):
    try: return client().containers.get(cname(bot_id))
    except NotFound: return None

def status(bot_id) -> str:
    c = _get(bot_id)
    return c.status if c else "stopped"

def stop(bot_id):
    c = _get(bot_id)
    if c: c.stop(timeout=10)

def remove_container(bot_id):
    c = _get(bot_id)
    if c: c.remove(force=True)

def logs(bot_id, tail=200) -> str:
    c = _get(bot_id)
    return c.logs(tail=tail, timestamps=True).decode("utf-8", "replace") if c else "(контейнер не запущен)"

def delete_all(bot_id):
    remove_container(bot_id)
    try: client().images.remove(tag(bot_id), force=True)
    except ImageNotFound: pass
    shutil.rmtree(bot_dir(bot_id), ignore_errors=True)

def running_count() -> int:
    return len(client().containers.list(filters={"label": "tgbot=1"}))
