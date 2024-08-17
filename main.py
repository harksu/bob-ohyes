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

container = None

async def setup_container():
    global container
    if container is None:
        container = client.containers.run(
            "python:slim",  
            detach=True,    
            tty=True        
        )
    return container

async def run_docker_command(command):
    container = await setup_container()
    try:
        exec_result = container.exec_run(f"bash -c '{command}'") 
        output = exec_result.output.decode('utf-8')
    except Exception as e:
        output = f"Error: {str(e)}"
    return output

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

@bot.command()
async def ohyes(ctx, *, command):
    try:
        if any(editor in command.split()[0] for editor in ["vim", "vi", "nano"]) and "install" not in command:
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
                    #여기서 나중에 cd 경로 추가해서 해당 경로에 무조건 가능하게해야됨
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
