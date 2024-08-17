import discord
from discord.ext import commands
import docker
from dotenv import load_dotenv
import os

load_dotenv()

# Docker 클라이언트 생성
client = docker.from_env()

# 봇의 프리픽스를 설정합니다 (예: !로 명령어 시작)
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 전역 변수로 컨테이너와 현재 작업 디렉토리 저장
container = None
current_directory = "/"

async def setup_container():
    global container
    if container is None:
        container = client.containers.run(
            "python:slim",  # Python slim 이미지
            detach=True,    # 백그라운드에서 실행
            tty=True        # 터미널 모드 활성화
        )
    return container

def normalize_path(path):
    # 여러 개의 슬래시를 하나로 정리하고, 절대 경로를 만듭니다.
    return os.path.normpath(path).replace("\\", "/")

async def run_docker_command(command):
    global current_directory
    container = await setup_container()
    try:
        # 현재 작업 디렉토리를 포함한 명령어 실행
        exec_result = container.exec_run(f"bash -c 'cd {current_directory} && {command}'")
        output = exec_result.output.decode('utf-8')
    except Exception as e:
        output = f"Error: {str(e)}"
    return output

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

@bot.command()
async def exec(ctx, *, command):
    global current_directory
    try:
        if command.startswith("cd "):
            # 디렉토리 변경 명령어일 경우
            new_directory = command[3:].strip()

            if new_directory == "..":
                # 상위 디렉토리로 이동 (cd ..)
                current_directory = normalize_path(os.path.dirname(current_directory.rstrip('/')))
                if not current_directory:
                    current_directory = "/"  # 루트 디렉토리로 이동
            else:
                # 새로운 디렉토리로 이동
                new_directory = normalize_path(os.path.join(current_directory, new_directory))  # 경로 결합
                container = await setup_container()
                exec_result = container.exec_run(f"bash -c 'cd {new_directory} && pwd'")
                if exec_result.exit_code == 0:
                    current_directory = new_directory
                else:
                    await ctx.send(f"Error: Unable to change directory to {new_directory}")
                    return

            await ctx.send(f"Changed directory to: {current_directory}")

        else:
            # 일반 명령어 실행
            await ctx.send(f"Executing command: {command}")
            output = await run_docker_command(command)
            if len(output) > 2000:
                # 디스코드 메시지 크기 제한을 초과하면 파일로 전송
                with open("output.txt", "w") as f:
                    f.write(output)
                await ctx.send("Output is too long to display in a single message. Here is the file:", file=discord.File("output.txt"))
            else:
                await ctx.send(f'```\n{output}\n```')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

# 디스코드 봇 토큰을 입력하세요
bot.run(os.getenv('APIKEY'))

@bot.event
async def on_disconnect():
    global container
    if container:
        container.stop()
        container.remove()
