import discord
from discord.ext import commands
import docker
from dotenv import load_dotenv
import os

load_dotenv()
print("just test")
# Docker 클라이언트 생성
client = docker.from_env()

# 봇의 프리픽스를 설정합니다 (예: !로 명령어 시작)
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 전역 변수로 컨테이너를 저장합니다
container = None

async def setup_container():
    global container
    if container is None:
        container = client.containers.run(
            "python:slim",  # Python slim 이미지
            detach=True,    # 백그라운드에서 실행
            tty=True        # 터미널 모드 활성화
        )
    return container

async def run_docker_command(command):
    container = await setup_container()
    try:
        # 명령어 실행
        exec_result = container.exec_run(f"bash -c '{command}'") #셸을 가져오는 방식
        output = exec_result.output.decode('utf-8')
    except Exception as e:
        output = f"Error: {str(e)}"
    return output

# 봇이 준비되었을 때 실행되는 코드
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

# 명령어를 실행하는 명령어 정의
@bot.command()
async def exec(ctx, *, command):
    try:
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

# 봇 종료 시 컨테이너 정리
@bot.event
async def on_disconnect():
    global container
    if container:
        container.stop()
        container.remove()
