from typing import *
from discord.ext import commands

class Nightcore(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    def on_ready(self):
        print("Nightcore Cog is loaded.")
    
    @commands.command(aliases=["nc"])
    async def nightcore(self, ctx: commands.Context):
        await ctx.send("Nightcore feature coming soon!")

def setup(bot: commands.Bot):
    bot.add_cog(Nightcore(bot))
