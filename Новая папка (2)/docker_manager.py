import os
import sys
import shutil
import asyncio
import json
import zipfile
from pathlib import Path
from typing import Optional, Dict, Tuple
from config import BOTS_DIR, DEFAULT_BOT_TEMPLATE, BASE_DIR
import database

class DockerManager:
    def __init__(self):
        self._docker_available: Optional[bool] = None
        self._local_processes: Dict[int, asyncio.subprocess.Process] = {}

    def get_bot_dir(self, user_id: int, bot_id: int) -> Path:
        bot_dir = BOTS_DIR / str(user_id) / str(bot_id)
        bot_dir.mkdir(parents=True, exist_ok=True)
        return bot_dir

    def ensure_default_files(self, user_id: int, bot_id: int):
        bot_dir = self.get_bot_dir(user_id, bot_id)
        main_py = bot_dir / "main.py"
        req_txt = bot_dir / "requirements.txt"
        dockerfile = bot_dir / "Dockerfile"

        if not main_py.exists():
            template_main = DEFAULT_BOT_TEMPLATE / "main.py"
            if template_main.exists():
                shutil.copy(template_main, main_py)
            else:
                main_py.write_text("# Welcome to Telegram Bot Hosting\nprint('Bot initialized')\n", encoding="utf-8")

        if not req_txt.exists():
            template_req = DEFAULT_BOT_TEMPLATE / "requirements.txt"
            if template_req.exists():
                shutil.copy(template_req, req_txt)
            else:
                req_txt.write_text("aiogram==3.17.0\n", encoding="utf-8")

        if not dockerfile.exists():
            dockerfile.write_text(
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt || true\n"
                "COPY . .\n"
                "ENV PYTHONUNBUFFERED=1\n"
                "CMD [\"python\", \"main.py\"]\n",
                encoding="utf-8"
            )

    async def check_docker(self) -> bool:
        if self._docker_available is not None:
            return self._docker_available
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            self._docker_available = (proc.returncode == 0)
        except Exception:
            self._docker_available = False
        return self._docker_available

    def get_container_name(self, bot_id: int) -> str:
        return f"tg_host_bot_{bot_id}"

    async def start_bot(self, bot: dict) -> Tuple[bool, str]:
        bot_id = bot["id"]
        user_id = bot["user_id"]
        bot_token = bot["bot_token"]
        env_vars = json.loads(bot.get("env_vars") or "{}")

        bot_dir = self.get_bot_dir(user_id, bot_id)
        self.ensure_default_files(user_id, bot_id)

        # Stop if already running
        await self.stop_bot(bot)

        await database.update_bot_status(bot_id, "STARTING")
        docker_ready = await self.check_docker()

        if docker_ready:
            container_name = self.get_container_name(bot_id)
            image_name = f"tg_bot_img_{bot_id}:latest"

            # 1. Build Docker Image
            build_proc = await asyncio.create_subprocess_exec(
                "docker", "build", "-t", image_name, str(bot_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await build_proc.communicate()
            if build_proc.returncode != 0:
                err_msg = stderr.decode(errors="replace") or stdout.decode(errors="replace")
                await database.update_bot_status(bot_id, "ERROR")
                await database.add_system_log(f"Docker build failed for bot {bot_id}: {err_msg[:300]}", bot_id, "ERROR")
                return False, f"Ошибка сборки Docker: {err_msg[:200]}"

            # 2. Run Container
            env_args = ["-e", f"BOT_TOKEN={bot_token}"]
            for k, v in env_vars.items():
                env_args.extend(["-e", f"{k}={v}"])

            run_cmd = [
                "docker", "run", "-d",
                "--name", container_name,
                "--restart", "unless-stopped",
                "--memory", "256m",
                "--cpus", "0.5",
                "-v", f"{bot_dir.resolve()}:/app",
                *env_args,
                image_name
            ]

            run_proc = await asyncio.create_subprocess_exec(
                *run_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await run_proc.communicate()
            if run_proc.returncode == 0:
                container_id = stdout.decode().strip()[:12]
                await database.update_bot_status(bot_id, "RUNNING", container_id)
                await database.add_system_log(f"Bot {bot_id} started in Docker container {container_id}", bot_id, "INFO")
                return True, "Бот успешно запущен в Docker!"
            else:
                err_msg = stderr.decode(errors="replace")
                await database.update_bot_status(bot_id, "ERROR")
                return False, f"Ошибка запуска Docker: {err_msg[:200]}"

        else:
            # Fallback: Process Isolation Runner
            log_file = bot_dir / "logs.txt"
            env = os.environ.copy()
            env["BOT_TOKEN"] = bot_token
            env["PYTHONUNBUFFERED"] = "1"
            for k, v in env_vars.items():
                env[k] = str(v)

            main_file = bot_dir / "main.py"
            if not main_file.exists():
                return False, "Файл main.py не найден в папке бота!"

            log_fp = open(log_file, "a", encoding="utf-8")
            log_fp.write(f"\n--- Bot Started at Process Mode ---\n")
            log_fp.flush()

            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, str(main_file),
                    cwd=str(bot_dir),
                    env=env,
                    stdout=log_fp,
                    stderr=log_fp
                )
                self._local_processes[bot_id] = proc
                pid_str = f"PID:{proc.pid}"
                await database.update_bot_status(bot_id, "RUNNING", pid_str)
                await database.add_system_log(f"Bot {bot_id} started in Process mode ({pid_str})", bot_id, "INFO")
                return True, "Бот запущен в режиме изолированного процесса!"
            except Exception as e:
                log_fp.close()
                await database.update_bot_status(bot_id, "ERROR")
                return False, f"Ошибка запуска процесса: {str(e)}"

    async def stop_bot(self, bot: dict) -> Tuple[bool, str]:
        bot_id = bot["id"]
        docker_ready = await self.check_docker()

        if docker_ready:
            container_name = self.get_container_name(bot_id)
            # Stop and remove container
            stop_proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await stop_proc.communicate()

        # Stop local process if running
        proc = self._local_processes.pop(bot_id, None)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    proc.kill()
            except Exception:
                pass

        await database.update_bot_status(bot_id, "STOPPED", None)
        await database.add_system_log(f"Bot {bot_id} stopped", bot_id, "INFO")
        return True, "Бот остановлен."

    async def restart_bot(self, bot: dict) -> Tuple[bool, str]:
        await self.stop_bot(bot)
        await asyncio.sleep(1)
        return await self.start_bot(bot)

    async def get_logs(self, bot: dict, lines: int = 150) -> str:
        bot_id = bot["id"]
        user_id = bot["user_id"]
        bot_dir = self.get_bot_dir(user_id, bot_id)

        docker_ready = await self.check_docker()
        if docker_ready:
            container_name = self.get_container_name(bot_id)
            proc = await asyncio.create_subprocess_exec(
                "docker", "logs", "--tail", str(lines), container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logs = stdout.decode(errors="replace") + stderr.decode(errors="replace")
                if logs.strip():
                    return logs

        # Check local process logs
        log_file = bot_dir / "logs.txt"
        if log_file.exists():
            try:
                content = log_file.read_text(encoding="utf-8", errors="replace")
                all_lines = content.splitlines()
                return "\n".join(all_lines[-lines:])
            except Exception as e:
                return f"Ошибка чтения логов: {e}"

        return "Логи пусты или бот еще не запускался."

    async def list_files(self, user_id: int, bot_id: int) -> list:
        bot_dir = self.get_bot_dir(user_id, bot_id)
        self.ensure_default_files(user_id, bot_id)
        files = []
        for p in bot_dir.rglob("*"):
            if p.is_file() and not p.name.startswith("."):
                rel_path = p.relative_to(bot_dir)
                files.append({
                    "name": str(rel_path).replace("\\", "/"),
                    "size": p.stat().st_size
                })
        return files

    async def save_uploaded_files(self, user_id: int, bot_id: int, filename: str, file_bytes: bytes):
        bot_dir = self.get_bot_dir(user_id, bot_id)
        if filename.endswith(".zip"):
            temp_zip = bot_dir / "upload_temp.zip"
            temp_zip.write_bytes(file_bytes)
            try:
                with zipfile.ZipFile(temp_zip, "r") as zf:
                    zf.extractall(bot_dir)
            finally:
                if temp_zip.exists():
                    temp_zip.unlink()
        else:
            target = bot_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file_bytes)

    async def cleanup_bot(self, bot: dict):
        await self.stop_bot(bot)
        user_id = bot["user_id"]
        bot_id = bot["id"]
        bot_dir = self.get_bot_dir(user_id, bot_id)
        if bot_dir.exists():
            shutil.rmtree(bot_dir, ignore_errors=True)

docker_mgr = DockerManager()
