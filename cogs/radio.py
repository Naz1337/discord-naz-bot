from typing import *
from discord.ext import commands


class Radio(commands.cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_ready(self):
        print("Radio Cog is loaded.")
    
    @commands.command()
    async def radio(self, ctx: commands.Context):
        await ctx.send("Coming soon!")


def setup(bot: commands.Bot):
    bot.add_cog(Radio(bot))
