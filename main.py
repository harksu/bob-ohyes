import discord
from discord.ext import commands
import docker
from dotenv import load_dotenv
import os
import subprocess
import logging
import shutil


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

# 전역 변수로 컨테이너와 현재 작업 디렉토리 저장
container = None
current_directory = "/"

async def setup_container():
    global container
    if container is None:
        container = client.containers.run(
            "python:slim",  
            detach=True,    
            tty=True        
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
async def ohyes(ctx, *, command):
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
        elif any(editor in command.split()[0] for editor in ["vim", "vi", "nano"]) and "install" not in command:
            logging.info("command에 'vim', 'vi', 'nano' 중 하나가 포함되어 있습니다.") 
            parts = command.split()
            filename = parts[1]
            if not os.path.exists(filename):
                with open(filename, 'w') as file:       
                    file.write(f"해당 파일은 bob13기 개발톤을 위한 데모 과정의 파일이며, 파일이름은 {filename}입니다")  
            is_vs_code_installed = shutil.which("code") is not None

            if is_vs_code_installed:
                notepad_process = subprocess.Popen(['code', '--wait', filename])
            else:
                notepad_process = subprocess.Popen(['notepad.exe', filename])      

            logging.info("notepad close wait ...")
            notepad_process.wait()

            try:
              with open(filename, 'r') as file:
                #여기서 파일 업로드 기능 합치기
                file_content = file.read()
                run_commnad = "echo"+" "+'"'+file_content+'"'+">"+filename
                await ctx.send(f"Executing command: {run_commnad}")
                output = await run_docker_command(run_commnad)
            except FileNotFoundError:
                logging.error("파일이 존재하지 않습니다. 저장을 제대로 했는지 확인하세요.")
                return 
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
