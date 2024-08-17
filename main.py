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
                    format='%(asctime)s - %(levellevelname)s - %(message)s',
                    handlers=[
                        logging.StreamHandler()
                    ])

client = docker.from_env()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

containers = {}  # 사용자별 컨테이너와 작업 디렉토리를 저장하는 딕셔너리

def normalize_path(path):
    return os.path.normpath(path).replace("\\", "/")

async def setup_container(user_id):
    container_name = f"container_{user_id}"
    try:
        container = client.containers.get(container_name)
        if container.status != 'running':
            container.start()
    except docker.errors.NotFound:
        container = client.containers.run(
            "python:slim",
            detach=True,
            tty=True,
            name=container_name,
            user="root"
        )
    except Exception as e:
        logging.error(f"Error setting up container for user {user_id}: {str(e)}")
        container = None

    if container:
        # 컨테이너가 처음 설정될 때만 /root로 초기화
        if user_id not in containers:
            containers[user_id] = {"container": container, "directory": "/root"}
        logging.debug(f"Container setup complete for user {user_id}, container name: {container_name}")
    else:
        logging.error(f"Failed to setup container for user {user_id}.")
    
    return container

async def run_docker_command(command, container, user_id):
    if container is None:
        logging.error(f"No container available for user {user_id}")
        return "Error: No container available."
    
    working_directory = containers[user_id]["directory"]  # 항상 최신의 작업 디렉토리를 가져옴
    try:
        exec_result = container.exec_run(f"bash -c 'cd {working_directory} && {command}'")
        output = exec_result.output.decode('utf-8', errors='ignore')
        logging.debug(f"Command executed: {command}, output: {output}")
    except Exception as e:
        output = f"Error: {str(e)}"
        logging.error(f"Error executing command: {command}, error: {str(e)}")
    return output

async def change_directory_command(ctx, command, container, user_id):
    new_directory = command[3:].strip()  # 'cd ' 이후의 경로를 추출
    working_directory = containers[user_id]["directory"]
    logging.debug(f"Attempting to change directory from {working_directory} to: {new_directory}")
    
    if not new_directory:  # new_directory가 공백이면 루트 디렉토리로 이동
        working_directory = "/"
    elif new_directory == "..":  # 상위 디렉토리로 이동
        working_directory = normalize_path(os.path.dirname(working_directory.rstrip('/')))
    else:
        # 주어진 경로로 이동을 시도
        new_directory = normalize_path(os.path.join(working_directory, new_directory))
        exec_result = container.exec_run(f"bash -c 'cd {new_directory} && pwd'")  # 실제로 이동했는지 확인하기 위해 pwd 사용
        
        if exec_result.exit_code == 0:
            working_directory = exec_result.output.decode('utf-8').strip()  # 정상적으로 이동한 경로로 설정
            logging.debug(f"Directory changed successfully to: {working_directory}")
        else:
            await ctx.send(f"Error: Unable to change directory to {new_directory}")
            logging.error(f"Failed to change directory to {new_directory}, exit code: {exec_result.exit_code}")
            return

    # 변경된 디렉토리를 저장
    containers[user_id]["directory"] = working_directory
    await ctx.send(f"Changed directory to: {working_directory}")

async def editor_file_command(ctx, command, container, user_id):
    filename = command.split()[1]
    working_directory = containers[user_id]["directory"]
    logging.debug(f"Editing file: {filename} in directory: {working_directory}")

    full_path = os.path.join(working_directory, filename)

    # 1. 파일 존재 여부 확인 및 기본 내용 설정
    await run_docker_command(f"if [ ! -f {full_path} ]; then touch {full_path}; fi", container, user_id)

    # 2. 파일 내용 읽기
    file_content = await run_docker_command(f"cat {full_path}", container, user_id)
    
    if not file_content.strip():  
        default_text = f"해당 파일은 bob13기 개발톤을 위한 데모 과정의 파일이며, 파일이름은 {filename}입니다"
        await run_docker_command(f"echo '{default_text}' > {full_path}", container, user_id)
        file_content = default_text  
        logging.debug(f"File {filename} was empty, added default text.")

    # 3. 파일을 로컬로 저장
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
        # 4. 파일 업로드 기다림
        msg = await bot.wait_for("message", check=check, timeout=300)
        if not msg.attachments:
            await ctx.send("파일 업로드가 되지 않았습니다.")
            logging.warning("No file uploaded by the user.")
            return

        # 5. 업로드된 파일 저장
        attachment = msg.attachments[0]
        await attachment.save(local_file_path)

        container_path = os.path.join(working_directory, filename)
        
        # 6. 파일을 컨테이너로 복사
        result = subprocess.run(["docker", "cp", local_file_path, f"{container.id}:{container_path}"], capture_output=True, text=True)
        if result.returncode != 0:
            logging.error(f"Failed to copy file to container: {result.stderr}")
            await ctx.send(f"Error: Failed to update file in container: {result.stderr}")
            return
        
        await ctx.send("파일이 성공적으로 업데이트되었습니다.")
        logging.debug(f"File {filename} updated successfully in container.")
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")
        logging.error(f"Error during file update: {str(e)}")

async def download_file_from_container(ctx, filename, container, user_id):
    working_directory = containers[user_id]["directory"]
    file_path = os.path.join(working_directory, filename)
    logging.debug(f"Downloading file: {filename} from directory: {working_directory}")
    
    try:
        # 1. 컨테이너에서 파일을 압축하여 가져오기
        tar_stream, _ = container.get_archive(file_path)
        file_obj = io.BytesIO()
        for chunk in tar_stream:
            file_obj.write(chunk)
        file_obj.seek(0)
        
        # 2. tar 파일에서 파일을 추출
        with tarfile.open(fileobj=file_obj) as tar:
            tar.extractall()

        # 3. 로컬 다운로드 경로 설정
        download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

        local_file_path = os.path.join(download_dir, filename)

        # tar.extractall()은 현재 디렉토리로 파일을 추출하므로, 원본 파일명을 바탕으로 파일명을 재설정
        extracted_file = os.path.join(os.getcwd(), filename)
        os.rename(extracted_file, local_file_path)

        # 4. Discord 채널로 파일 전송
        await ctx.send(file=discord.File(local_file_path))
        logging.debug(f"File {filename} downloaded successfully.")
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")
        logging.error(f"Error downloading file: {filename}, error: {str(e)}")

def upload_file_to_container(container, file_data, filename, destination_path, user_id):
    if container is None:
        logging.error(f"No container available for file upload for user {user_id}")
        return "Error: No container available for file upload."
    
    working_directory = containers[user_id]["directory"]
    try:
        # tar로 압축
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            tarinfo = tarfile.TarInfo(name=os.path.basename(destination_path))
            tarinfo.size = len(file_data)
            tar.addfile(tarinfo, io.BytesIO(file_data))
        tar_stream.seek(0)

        # 압축 파일을 Docker 컨테이너에 업로드
        container.put_archive(working_directory, tar_stream)
        logging.debug(f"File {filename} uploaded successfully to {destination_path}")
        return f"File {filename} uploaded successfully to {destination_path}"
    except Exception as e:
        logging.error(f"Error uploading file to container: {str(e)}")
        return f"Error: {str(e)}"

@bot.event
async def on_message(message):
    # 파일 업로드 처리만 전담
    if message.attachments and not message.content.startswith("!ohyes download"):
        for attachment in message.attachments:
            file_data = await attachment.read()
            user_id = message.author.id
            container = await setup_container(user_id)

            if container is None:
                await message.channel.send(f"Error: Could not setup container for user {user_id}.")
                return

            working_directory = containers[user_id]["directory"]
            destination_path = os.path.join(working_directory, attachment.filename)

            upload_result = upload_file_to_container(container, file_data, attachment.filename, destination_path, user_id)
            await message.channel.send(upload_result)

    # 다른 명령어들을 처리
    await bot.process_commands(message)

@bot.command()
async def ohyes(ctx, *, command=None):
    user_id = ctx.author.id
    container = await setup_container(user_id)
    
    if container is None:
        await ctx.send(f"Error: Could not setup container for user {user_id}.")
        return
    
    try:
        if command.startswith("download "):
            filename = command.split(" ")[1]
            await download_file_from_container(ctx, filename, container, user_id)
        elif command.startswith("cd "):
            await change_directory_command(ctx, command, container, user_id)
        elif any(editor in command.split()[0] for editor in ["vim", "vi", "nano"]) and "install" not in command:
            await editor_file_command(ctx, command, container, user_id)
        else:
            if command == "cd":
                await change_directory_command(ctx, "cd /", container, user_id)
                return
            await ctx.send(f"Executing command: {command}")
            output = await run_docker_command(command, container, user_id)
            if len(output) > 2000:
                with open("output.txt", "w") as f:
                    f.write(output)
                await ctx.send("Output is too long to display in a single message. Here is the file:", file=discord.File("output.txt"))
            else:
                await ctx.send(f'```\n{output}\n```')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')
        logging.error(f"Error executing ohyes command: {str(e)}")

@bot.event
async def on_disconnect():
    for user_id, data in containers.items():
        container = data["container"]
        if container:
            container.stop()
            container.remove()

bot.run(os.getenv('APIKEY'))
