import json
import audioop
import discord
import requests
import threading
from queue import Queue, Empty as EmptyQueue
from typing import *
from subprocess import Popen, PIPE
from functools import partial
from discord.ext import commands
from discord.ext.commands import CommandError


class RadioPlayer(discord.AudioSource):
    """The radio player class"""

    def __init__(self, radio_code_name: str, radio_name: str, radio_url: str, radio_format: str, discord_ctx: commands.Context):
        # TODO: add support for non icy stream

        self.radio_code_name = radio_code_name
        self.radio_name = radio_name 
        self.radio_url = radio_url
        self.radio_format = radio_format
        self.discord_ctx = discord_ctx
        self._volume = 0.07
        self.audio_queue = Queue()

        ffmpeg_command_line = "ffmpeg -f {audio_format} -i pipe:0 -f s16le -ac 2 -ar 48000 pipe:1".format(audio_format=radio_format).split()

        self.ffmpeg_process = Popen(ffmpeg_command_line, stdin=PIPE, stdout=PIPE, creationflags=0x08000000)
        # the creationflags part is only if this is running in Windows

        # Threading!
        stdin_thread = threading.Thread(target=self.stdin_blaster, daemon=True)
        stdout_thread = threading.Thread(target=self.drain_stdout, daemon=True)

        stdin_thread.start()
        stdout_thread.start()


    def drain_stdout(self):
        stdout: IO = self.ffmpeg_process.stdout
        while True:
            data = stdout.read(3840)
            if not data:
                break
            self.audio_queue.put(data)
    
    def stdin_blaster(self):
        stdin: IO = self.ffmpeg_process.stdin
        headers = {"Icy-MetaData": "1"}
        with requests.get(self.radio_url, headers=headers, stream=True) as response:
            response.raise_for_status()

            metaint: int = int(response.headers.get("icy-metaint"))
            try:
                data = response.raw.read(metaint)
                while True:
                    stdin.write(data)
                    
                    metadata_block_size = int.from_bytes(response.raw.read(1), byteorder="little")
                    if metadata_block_size != 0:
                        metadata_bytes: bytes = response.raw.read(metadata_block_size * 16)
                        self.print_what_is_playing(metadata_bytes.decode("utf-8"))
                        # TODO: Tell what is currently playing in the text channel
                    
                    data = response.raw.read(metaint)
            except OSError:
                # ffmpeg closed
                return
    
    @property
    def volume(self):
        return self._volume
    
    @volume.setter
    def volume(self, value: float):
        self._volume = min(1.0, value)

    def print_what_is_playing(self, metadata_string: str):
        """Temp func until able to tell what is playing in the text channel"""
        metadatas = metadata_string.split(";")
        for metadata_line in metadatas:
            metadata_line_pair = metadata_line.split("=")
            if metadata_line_pair[0] == "StreamTitle":
                print("Currently playing {song_name} in {server_name}".format(song_name=metadata_line_pair[1].strip("'"), server_name=self.discord_ctx.guild))
                break

    def read(self):
        try:
            return audioop.mul(self.audio_queue.get(timeout=15), 2, self._volume)
        except EmptyQueue:
            return b''
    
    def cleanup(self):
        self.ffmpeg_process.terminate()
        self.audio_queue = None
        self = None



class Radio(commands.Cog):
    """Radio Cog Class"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("Radio Cog is loaded.")

    @commands.command()
    async def radio(self, ctx: commands.Context, radio_code_name: str):
        """Command to play a radio"""

        radio_data = await self.bot.loop.run_in_executor(None, partial(self.get_radio, radio_code_name))

        # There are always 3 element in radio_data, [0] is the url
        # [1] is the format and [2] is the radio name

        if not radio_data:
            return await ctx.send(f"There is no such thing as {radio_code_name}")
        
        player = await self.bot.loop.run_in_executor(None, partial(RadioPlayer, radio_code_name, radio_data[2], radio_data[0], radio_data[1], ctx))

        ctx.voice_client.play(player)

    @commands.command()
    async def stop_radio(self, ctx: commands.Context):
        voice_client: discord.VoiceClient = ctx.voice_client
        if voice_client.is_playing():
            voice_client.stop()
        await ctx.send("Stopped radio!")
    
    @commands.command()
    async def radio_volume(self, ctx: commands.Context, volume: int):
        try:
            voice_client: discord.VoiceClient = ctx.voice_client
            voice_client.source.volume = float(volume / 100)
        except AttributeError as e:
            await ctx.send("Failed to change volume")
            raise e
        await ctx.send(f"Changed volume to {volume}")

    @radio.before_invoke
    async def radio_before_invoke(self, ctx: commands.Context):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
                print(
                    f"Connected to the {ctx.author}'s voice channel on {ctx.guild} server!")
            else:
                await ctx.send("Please join a VC first!")
                raise CommandError(
                    f"{ctx.author} tried to summon bot while being outside of VC.")

        # This part is to check if it need to stop the current player
        # or not by checking either if it the user is asking to listen to
        # currently playing radio station or if it is not radio player at all
        elif ctx.voice_client.is_playing():
            if ctx.voice_client.source is RadioPlayer:
                radio_player: RadioPlayer = ctx.voice_client.source
                # check if currently playing station is the same
                # as the one being asked to tuned into
                # ctx.args[2] is the radio_name argument of the radio command
                if radio_player.radio_code_name == ctx.args[2]:
                    await ctx.send(f"Already tuned to {ctx.args[2]}!")
                    raise CommandError(
                        f"User {ctx.author} tried to tune into the currently tuned radio station.")
            # if we reached here, it means that the source is either some type of other source/player
            # or its a different station, either way, we just stop them
            ctx.voice_client.stop()

    def get_radio(_, radio_name: str) -> Union[Dict, bool]:
        with open("data/radios.json") as json_file:
            radios: Dict = json.load(json_file)

        try:
            return radios[radio_name]
        except:
            return False


def setup(bot: commands.Bot):
    bot.add_cog(Radio(bot))
