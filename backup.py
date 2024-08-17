import discord
from discord.ext import commands
import docker
from dotenv import load_dotenv
import os
import tarfile
import io

load_dotenv()
current_directory = "/"
client = docker.from_env()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

container = None

async def setup_container():
    global container
    if container is None:
        container = client.containers.run(
            "python:slim",
            detach=True,
            tty=True,
            environment={"LANG":"ko_KR.UTF-8"}
        )
    return container

async def run_docker_command(command):
    global current_directory
    container = await setup_container()
    try:
        # 명령어 실행
        exec_result = container.exec_run(f"bash -c 'cd {current_directory} && {command}'") # 셸을 가져오는 방식
        output = exec_result.output.decode('utf-8', errors='ignore')
    except Exception as e:
        output = f"Error: {str(e)}"
    return output

def normalize_path(path):
    # 여러 개의 슬래시를 하나로 정리하고, 절대 경로를 만듭니다.
    return os.path.normpath(path).replace("\\", "/")

# 봇이 준비되었을 때 실행되는 코드
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

# 명령어를 실행하는 명령어 정의
@bot.command()
async def exec(ctx, *, command = None):
    global current_directory
    try:
        if ctx.message.attachments:
            print("success")
        else:
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
                    with open("output.txt", "w", encoding='utf-8') as f:
                        f.write(output)
                    await ctx.send("Output is too long to display in a single message. Here is the file:", file=discord.File("output.txt"))
                else:
                    await ctx.send(f'```\n{output}\n```')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')


#파일을 tar로 Docker에 업로드
def upload_file_to_container(container, file_data, filename, destination_path):
    try:
        #tar로 압축
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            tarinfo = tarfile.TarInfo(name=os.path.basename(destination_path))
            tarinfo.size = len(file_data)
            tar.addfile(tarinfo, io.BytesIO(file_data))
            #tar.add(file_path, arcname=os.path.basename(destination_path))
        tar_stream.seek(0)

        #압축 파일을 Docker 컨테이너에 업로드
        container.put_archive(current_directory, tar_stream)
        #return f"File {os.path.basename(file_path)} uploaded successfully to {destination_path}"
        return f"File {filename} uploaded successfully to {destination_path}"
    except Exception as e:
        return f"Error: {str(e)}"

#파일 업로드 시 호출
@bot.event
async def on_message(message):
    if message.attachments:
        for attachment in message.attachments:
            file_data = await attachment.read()

            #Docke에 파일 업로드
            container = await setup_container()

            #현재 위치를 결정
            current_directory = os.getcwd()

            #루트가 아닌 경우 경로 설정
            if current_directory != '/':
                destination_path = f"{current_directory}/{attachment.filename}"  #컨테이너 내 경로
            else:
                destination_path = f"/{attachment.filename}"  #컨테이너 내 경로

            upload_result = upload_file_to_container(container, file_data, attachment.filename, destination_path)

            await message.channel.send(upload_result)
    
    await bot.process_commands(message)

# 디스코드 봇 토큰을 입력하세요
bot.run(os.getenv('APIKEY'))

# 봇 종료 시 컨테이너 정리
@bot.event
async def on_disconnect():
    global container
    if container:
        container.stop()
        container.remove()