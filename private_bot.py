import discord
from discord.ext import commands
import docker
from dotenv import load_dotenv
import os
import json

load_dotenv()

client = docker.from_env()
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
containers = {}

async def setup_container(user_id):
    global containers
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
    containers[user_id] = container
    return container

async def run_docker_command(container, command, user_dir=None):
    try:
        working_directory = user_dir if user_dir else "/root"
        exec_command = f"bash -c 'cd {working_directory} && {command}'"
        exec_id = container.exec_run(exec_command, stdout=True, stderr=True)
        output = exec_id.output.decode('utf-8')
    except Exception as e:
        output = f"Error: {str(e)}"
    return output

async def handle_command(ctx, command):
    user_id = ctx.author.id
    username = ctx.author.name
    container = await setup_container(user_id)
    await ctx.send(f"Executing command as root: {command}")
    output = await run_docker_command(container, command)
    if len(output) > 2000:
        with open("output.txt", "w") as f:
            f.write(output)
        await ctx.send("Output is too long to display in a single message. Here is the file:", file=discord.File("output.txt"))
    else:
        await ctx.send(f'```\n{output}\n```')

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

@bot.command()
async def ohyes(ctx, *, command):
    try:
        await handle_command(ctx, command)
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.event
async def on_disconnect():
    global containers
    for container in containers.values():
        container.stop()
        container.remove()

bot.run(os.getenv('APIKEY1'))
