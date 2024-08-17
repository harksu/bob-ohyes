import discord
from discord.ext import commands
import docker
from dotenv import load_dotenv
import os
import tarfile
import io
import logging
import subprocess

load_dotenv()

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.StreamHandler()
                    ])

client = docker.from_env()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

container = None
current_directory = "/"

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

def normalize_path(path):
    return os.path.normpath(path).replace("\\", "/")

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

async def change_directory_command(ctx, command):
    global current_directory
    new_directory = command[3:].strip()

    if new_directory == "..":
        current_directory = normalize_path(os.path.dirname(current_directory.rstrip('/')))
        if not current_directory:
            current_directory = "/"
    else:
        new_directory = normalize_path(os.path.join(current_directory, new_directory))
        container = await setup_container()
        exec_result = container.exec_run(f"bash -c 'cd {new_directory} && pwd'")
        if exec_result.exit_code == 0:
            current_directory = new_directory
        else:
            await ctx.send(f"Error: Unable to change directory to {new_directory}")
            return

    await ctx.send(f"Changed directory to: {current_directory}")

async def editor_file_command(ctx, command):
    parts = command.split()
    filename = parts[1]

    full_path = os.path.join(current_directory, filename)

    await run_docker_command(f"if [ ! -f {full_path} ]; then touch {full_path}; fi")

    file_content = await run_docker_command(f"cat {full_path}")
    
    if not file_content.strip():  
        default_text = f"해당 파일은 bob13기 개발톤을 위한 데모 과정의 파일이며, 파일이름은 {filename}입니다"
        await run_docker_command(f"echo '{default_text}' > {full_path}")
        file_content = default_text  

    # 사용자의 기본 다운로드 경로를 찾음
    download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    local_file_path = os.path.join(download_dir, filename)
    
    with open(local_file_path, "w") as f:
        f.write(file_content)
    
    await ctx.send(file=discord.File(local_file_path))
    await ctx.send("파일을 편집한 후 업로드 해주세요.")

    def check(msg):
        return msg.author == ctx.author and msg.attachments

    try:
        msg = await bot.wait_for("message", check=check, timeout=300) 
        attachment = msg.attachments[0]
        await attachment.save(local_file_path)

        container = await setup_container()
        container_path = os.path.join(current_directory, filename)
        
        subprocess.run(["docker", "cp", local_file_path, f"{container.id}:{container_path}"], check=True)
        
        await ctx.send("파일이 성공적으로 업데이트되었습니다.")
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    global current_directory

@bot.command()

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

async def ohyes(ctx, *, command):
    try:
        if command.startswith("cd "):
            await change_directory_command(ctx, command)
        elif any(editor in command.split()[0] for editor in ["vim", "vi", "nano"]) and "install" not in command:
            await editor_file_command(ctx, command)
        else:
            await ctx.send(f"Executing command: {command}")
            output = await run_docker_command(command)
            if len(output) > 2000:
                with open("output.txt", "w") as f:
                    f.write(output)
                await ctx.send("Output is too long to display in a single message. Here is the file:", file=discord.File("output.txt"))
            else:
                await ctx.send(f'```\n{output}\n```')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

bot.run(os.getenv('APIKEY'))

@bot.event
async def on_disconnect():
    global container
    if container:
        container.stop()
        container.remove()