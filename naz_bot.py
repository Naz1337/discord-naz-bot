import os
import random
from typing import *
from discord import Intents
from discord.ext import commands

# BOT DECLARATION
bot = commands.Bot(command_prefix="$",
                   description="Bot that Naz made.", intents=Intents.all())

# BOT EVENTS


@bot.event
async def on_ready():
    print(
        "Bot is ready!\n"
        f"Bot username: {bot.user}"
    )


# BOT COMMANDS
# COMMAND ERROR HANDLER MUST BE CODED BELOW THAT COMMAND


@bot.command(name="ping", pass_context=True)
async def ping(ctx: commands.Context):
    await ctx.send(f"Pong! {int(bot.latency*1000)}ms")


@bot.command(aliases=["roll"])
async def random_number(ctx: commands.Context, max: int):
    await ctx.send(
        f"Random generated number for you is {random.randint(0, max + 1)}"
    )


@random_number.error
async def random_number_error(ctx: commands.Context, error):
    print("Error", type(error))
    print(error)
    await ctx.send(
        "Command usage is wrong!\n"
        "Usage: $roll [number]"
    )


@bot.command(aliases=["rld"])
@commands.is_owner()
async def reload(ctx: commands.Context, extension_name: str):
    bot.reload_extension(f"cogs.{extension_name}")

    await ctx.send(f"Successfully reloaded {extension_name}")


@reload.error
async def reload_error(ctx: commands.Context, error):
    if isinstance(error, commands.NotOwner):
        await ctx.send("You do not have enough power to access this command.")


# UTILITY FUNCTION


# CODE TO RUN BEFORE STARTING BOT
for filename in os.listdir("./cogs"):
    if filename.endswith(".py"):
        print(f"Loading {filename}")
        bot.load_extension(f"cogs.{filename[:-3]}")

bot.run(os.getenv("DISCORDBOTAPIKEY"))
