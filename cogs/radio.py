import discord
from typing import *
from discord.ext import commands
from discord.ext.commands import CommandError


class RadioPlayer(discord.AudioSource):
    """The radio player class"""

    def __init__(self, radio_name: str):
        self.radio_name = radio_name


class Radio(commands.Cog):
    """Radio Cog Class"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("Radio Cog is loaded.")

    @commands.command()
    async def radio(self, ctx: commands.Context, radio_name: str):
        pass
    
    @radio.before_invoke
    async def radio_before_invoke(self, ctx: commands.Context):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
                print(f"Connected to the {ctx.author}'s voice channel on {ctx.guild} server!")
            else:
                await ctx.send("Please join a VC first!")
                raise CommandError(f"{ctx.author} tried to summon bot while being outside of VC.")
        
        # This part is to check if it need to stop the current player
        # or not by checking either if it the user is asking to listen to
        # currently playing radio station or if it is not radio player at all
        elif ctx.voice_client.is_playing():
            if ctx.voice_client.source is RadioPlayer:
                # check if currently playing station is the same
                # as the one being asked to tuned into
                if ctx.voice_client.source.radio_name == ctx.args[2]:  # ctx.args[2] is the radio_name argument of the radio command
                    await ctx.send(f"Already tuned to {ctx.args[2]}!")
                    raise CommandError(f"User {ctx.author} tried to tune into the currently tuned radio station.")
            # if we reached here, it means that the source is either some type of other source/player
            # or its a different station, either way, we just stop them
            ctx.voice_client.stop()

        


def setup(bot: commands.Bot):
    bot.add_cog(Radio(bot))
