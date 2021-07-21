import os
import random
from typing import *
from discord import Intents
from discord.ext import commands


class NazBot(commands.Bot):
    """Naz Bot Class"""

    def __init__(self):
        super().__init__(command_prefix="$",
                         description="Bot that Naz made.", intents=Intents.all())

        self.add_commands()

        # load cogs
        # self.load_cogs()

    async def on_ready(self):
        print(
            "Bot is ready!\n"
            f"Bot username: {self.user}"
        )

    def add_commands(self):
        """Guide for error handling a command

        error handling function for that command must be defined below that command thank you."""

        @self.command(name="ping", pass_context=True)
        async def ping(ctx: commands.Context):
            await ctx.send(f"Pong! {int(self.latency*1000)}ms")

        @self.command(aliases=["roll"])
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

        @self.command(aliases=["rld"])
        @commands.is_owner()
        async def reload(ctx: commands.Context, extension_name: str):
            self.reload_extension(f"cogs.{extension_name}")

            await ctx.send(f"Successfully reloaded {extension_name}")

        @reload.error
        async def reload_error(ctx: commands.Context, error):
            if isinstance(error, commands.NotOwner):
                await ctx.send("You do not have enough power to access this command.")

    # def load_cogs(self):
    #     for filename in os.listdir("./cogs"):
    #         if filename.endswith(".py"):
    #             self.load_extension(f"cogs.{filename[:-3]}")


naz_bot = NazBot()
naz_bot.run(os.getenv("DISCORDBOTAPIKEY"))
