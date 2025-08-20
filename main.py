import discord
import logging
import os
import asyncio
import uuid
from discord.ext import commands
from dotenv import load_dotenv
from langgraph_sdk import get_client
from langgraph_sdk.schema import Thread

load_dotenv()

DISCORD_MAX_LENGTH = 2000  # Discord message character limit
SHARED_THREAD_NAME = "Recipe Bot Convo"

ROLES = {
    "HEAD_CHEF": "Head Chef",
    "CHEF": "Chef",
    "TRAINEE": "Trainee"
}

token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='event_server/logs/discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
new_role = ROLES["TRAINEE"]

_LANGGRAPH_CLIENT = get_client(url=os.environ["ASSISTANT_URL"])

async def missing_role_error(ctx, error):
    """ Handle missing role errors for commands that require specific roles. """
    if isinstance(error, commands.MissingRole):
        await ctx.send("You don't have permission to use add recipe")

@bot.event
async def on_ready():
    print('bot is ready')

async def _get_shared_thread(ctx) -> discord.Thread:
    """Finds or creates a shared Discord thread for the entire guild.

    This function iterates through all active threads in the channel and
    returns the one with a predefined name if it exists. If not, it creates a new one.

    Args:
        ctx: The context of the command.

    Returns:
        discord.Thread: The shared thread for the guild.
    """
    # Check if the command was sent in a server channel
    if not isinstance(ctx.channel, discord.TextChannel):
        # If it's a DM or private thread, just use the current channel
        return ctx.channel

    # Check for an existing shared thread
    for thread in ctx.channel.threads:
        if thread.name == SHARED_THREAD_NAME:
            return thread

    # If no existing thread is found, create a new one
    return await ctx.channel.create_thread(name=SHARED_THREAD_NAME)
    
async def _create_or_fetch_lg_thread(thread_id: uuid.UUID) -> Thread:
    """Create or fetch a LangGraph thread for the given thread ID.

    This function attempts to fetch an existing LangGraph thread. If it doesn't
    exist, a new thread is created.

    Args:
        thread_id (uuid.UUID): The unique identifier for the thread.

    Returns:
        Thread: The LangGraph thread object.
    """
    try:
        return await _LANGGRAPH_CLIENT.threads.get(thread_id)
    except Exception:
        pass
    return await _LANGGRAPH_CLIENT.threads.create(thread_id=thread_id)

@bot.event
async def on_member_join(member):
    """ Send a welcome message to new members when they join the server. """
    await member.send(f"Welcome to the server, {member.name}!")

@bot.event
async def on_message(message):
    """ Process incoming messages and handle attachments. """
    if message.author == bot.user:
        return
    if message.attachments:
        for attachment in message.attachments:
            print(attachment)   # TODO: Could potentially be used to add recipes from attachments
    await bot.process_commands(message)

@bot.command()
async def recipe(ctx, *, question: str = None):
    """ Handle the !recipe command to get recipe-related answers. 
    Also handles long responses by splitting them into multiple messages.
    Also creates or fetches a LangGraph thread for the conversation.

    Usage: !recipe <your question>

    Args:
        ctx: The context of the command.
        question (str): The user's question about recipes.
    """
    # Check if a question was provided
    if not question:
        thread = await _get_shared_thread(ctx)
        await thread.send("Please provide a question. Usage: `!recipe <your question>`")
        return
    
    async with ctx.typing():
        guild_id = ctx.guild.id if ctx.guild else None
        thread = await _get_shared_thread(ctx)
        lg_thread = await _create_or_fetch_lg_thread(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"DISCORD_GUILD:{guild_id}")
        )
        thread_id = lg_thread["thread_id"]
        user_id = ctx.author.id
        run_result = await _LANGGRAPH_CLIENT.runs.wait(
            thread_id,
            input={"question": question},
            config={
                "configurable": {
                    "user_id": user_id,
                }
            },
        )
        bot_message = run_result["messages"][-1]
        response = bot_message["content"]

        # Check if the response is too long
        if len(response) > DISCORD_MAX_LENGTH:
            # Split the response into chunks
            chunks = []
            current_chunk = ""
            for line in response.splitlines(True): # splitlines(True) keeps the newline characters
                if len(current_chunk) + len(line) > DISCORD_MAX_LENGTH:
                    chunks.append(current_chunk)
                    current_chunk = line
                else:
                    current_chunk += line
            chunks.append(current_chunk) # Append the last chunk

            # Send each chunk as a separate message
            for chunk in chunks:
                try:
                    await thread.send(chunk)
                except discord.errors.HTTPException as e:
                    print(f"An error occurred while sending a chunk: {e}")
                await asyncio.sleep(1)  # avoid rate limits
        else:
            # If the response is short enough, send it as one message
            try:
                await thread.send(response)
            except discord.errors.HTTPException as e:
                print(f"An error occurred while sending the message: {e}")

@recipe.error
async def recipe_error(ctx, error):
    """ Handle errors for the recipe command. """
    await ctx.send(f"An error occurred: {str(error)}")

@bot.command()
@commands.has_role(ROLES["HEAD_CHEF"])
async def assign(ctx, assigned_role: str, target_user: discord.Member):
    """
    Assigns a role to a specified user.

    Usage: !assign <role_name> <@user>
    """

    role_name = ROLES.get(assigned_role.upper())
    if not role_name:
        await ctx.send(f"The role '{assigned_role}' is not a valid role to assign.")
        return

    role_to_assign = discord.utils.get(ctx.guild.roles, name=role_name)

    if not role_to_assign:
        await ctx.send(f"The role '{role_name}' does not exist on this server.")
        return

    try:
        await target_user.add_roles(role_to_assign)
        await ctx.send(f"Successfully assigned the role '{role_to_assign.name}' to {target_user.mention}.")
    except discord.Forbidden:
        await ctx.send("I do not have the necessary permissions to assign that role.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")

@assign.error
async def assign_error(ctx, error):
    """ Handle errors for the assign command. """
    if isinstance(error, commands.MissingRole):
        await ctx.send("You don't have a permission to assign roles")

@bot.command()
async def remove(ctx):
    role = discord.utils.get(ctx.guild.roles, name=new_role)
    if role:
        await ctx.author.remove_roles(role)
        await ctx.send(f"{ctx.author.mention} is no longer a {new_role}!")
    else:
        await ctx.send("Role doesn't exist")

@bot.command()
async def dm(ctx, *, msg):
    await ctx.author.send(f"You said {msg}")

@bot.command()
async def reply(ctx):
    await ctx.reply("This is a reply")

@bot.command()
@commands.has_role("Head Chef")
async def add_recipe(ctx):
    await ctx.send("You will be able to add recipe in the future")

@add_recipe.error
async def secret_error(ctx, error):
    return await missing_role_error(ctx, error)

if __name__ == '__main__':
    bot.run(token, log_handler=handler, log_level=logging.DEBUG)