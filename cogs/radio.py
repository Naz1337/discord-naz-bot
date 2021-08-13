import json
import array
import struct
import audioop
import discord
import asyncio
import requests
import threading
from io import BufferedIOBase, BytesIO
from queue import Queue, Empty as EmptyQueue
from typing import *
from subprocess import Popen, PIPE
from functools import partial
from discord.ext import commands, tasks
from discord.ext.commands import CommandError


class OggVorbisStream:

    def __init__(self, file_handle: BufferedIOBase) -> None:
        self.page_iter = self.page_generator(file_handle)

    def page_generator(self, file_handle: BufferedIOBase):
        while file_handle.read(4) == b"OggS":
            yield OggPage(file_handle)

    def get_next_page(self):
        try:
            return next(self.page_iter)
        except StopIteration:
            return None


class OggPage:

    ogg_page_struct = struct.Struct("=BBQIIIB")

    def __init__(self, file_handle: BufferedIOBase) -> None:
        self.version, self.mode, self.granule, self.serial, self.page_no, self.crc, self.len_seg_table = self.ogg_page_struct.unpack(
            file_handle.read(self.ogg_page_struct.size))

        self.seg_table = array.array('B', struct.unpack(
            'B'*self.len_seg_table, file_handle.read(self.len_seg_table)))

        self.data = file_handle.read(sum(self.seg_table))

    def convert_to_bytes(self):
        return b"OggS" + self.ogg_page_struct.pack(self.version, self.mode, self.granule, self.serial, self.page_no, self.crc, self.len_seg_table) + self.seg_table.tobytes() + self.data


class RadioPlayer(discord.AudioSource):
    """The radio player class"""

    def __init__(self, radio_code_name: str, radio_name: str, radio_url: str, radio_format: str, discord_ctx: commands.Context):
        self.radio_code_name = radio_code_name
        self.radio_name = radio_name
        self.radio_url = radio_url
        self.radio_format = radio_format

        self.discord_ctx = discord_ctx
        self.event_loop: asyncio.AbstractEventLoop = discord_ctx.bot.loop
        self.last_now_playing_message: discord.Message = None

        self._volume = 0.07
        self.audio_queue = Queue()

        if self.radio_format == "direct":
            ffmpeg_command_line = "ffmpeg -i {url} -f s16le -ac 2 -ar 48000 pipe:1".format(
                url=radio_url).split()

            self.ffmpeg_process = Popen(
                ffmpeg_command_line, stdout=PIPE, creationflags=0x08000000)
        else:
            ffmpeg_command_line = "ffmpeg -i pipe:0 -f s16le -ac 2 -ar 48000 pipe:1".split()

            self.ffmpeg_process = Popen(
                ffmpeg_command_line, stdin=PIPE, stdout=PIPE, creationflags=0x08000000)
            # the creationflags part is only if this is running in Windows

            # Threading!
            stdin_thread = threading.Thread(
                target=self.stdin_blaster, daemon=True)
            stdin_thread.start()
        stdout_thread = threading.Thread(target=self.drain_stdout, daemon=True)
        stdout_thread.start()

        self.setup_auto_disconnect()

    def drain_stdout(self):
        stdout: IO = self.ffmpeg_process.stdout
        while True:
            data = stdout.read(3840)
            if not data:
                break
            try:
                self.audio_queue.put(data)
            except AttributeError:
                return

    def stdin_blaster(self):
        stdin: IO = self.ffmpeg_process.stdin
        if self.radio_format != "vorbis":
            headers = {"Icy-MetaData": "1"}
            with requests.get(self.radio_url, headers=headers, stream=True) as response:
                response.raise_for_status()

                metaint: int = int(response.headers.get("icy-metaint"))
                try:
                    data = response.raw.read(metaint)
                    while True:
                        stdin.write(data)

                        metadata_block_size = int.from_bytes(
                            response.raw.read(1), byteorder="little")
                        if metadata_block_size != 0:
                            metadata_bytes: bytes = response.raw.read(
                                metadata_block_size * 16)
                            self.event_loop.create_task(
                                self.tell_text_channel_currently_playing(metadata_bytes.decode("utf-8")))

                        data = response.raw.read(metaint)
                except OSError:
                    # ffmpeg closed
                    return
        else:
            with requests.get(self.radio_url, stream=True) as response:
                response.raise_for_status()

                ogg_stream = OggVorbisStream(response.raw)

                page = ogg_stream.get_next_page()

                while page:
                    if page.data[:7] == b"\x03vorbis":
                        metadata = dict()

                        data_io = BytesIO(page.data)

                        data_io.read(7)

                        data_io.read(int.from_bytes(
                            data_io.read(4), "little", signed=False))

                        for _ in range(int.from_bytes(data_io.read(4), "little", signed=False)):
                            separated_metadata = data_io.read(int.from_bytes(
                                data_io.read(4), "little", signed=False)).decode().split('=')
                            metadata[separated_metadata[0].lower()] = "=".join(
                                separated_metadata[1:])

                        del data_io

                        self.event_loop.create_task(self.tell_np_vorbis(metadata))

                        del metadata

                    try:
                        stdin.write(page.convert_to_bytes())
                    except OSError:
                        return

                    page = ogg_stream.get_next_page()

    async def tell_np_vorbis(self, metadata: Dict):
        if self.last_now_playing_message:
            await self.last_now_playing_message.delete()
        self.last_now_playing_message = await self.discord_ctx.send(f"Now playing {metadata['artist']} - {metadata['title']} from {self.radio_name}")

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = min(1.0, value)

    def get_current_song_title(self, metadata_string: str):
        """Temp func until able to tell what is playing in the text channel"""
        metadatas = metadata_string.split(";")
        for metadata_line in metadatas:
            metadata_line_pair = metadata_line.split("=")
            if metadata_line_pair[0] == "StreamTitle":
                # print("Currently playing {song_name} in {server_name}".format(
                #     song_name=metadata_line_pair[1].strip("'"), server_name=self.discord_ctx.guild))
                # break
                return metadata_line_pair[1].strip("'")

    async def tell_text_channel_currently_playing(self, metadata: str):
        song_name = await self.event_loop.run_in_executor(None, partial(self.get_current_song_title, metadata))
        if self.last_now_playing_message:
            await self.last_now_playing_message.delete()
        self.last_now_playing_message = await self.discord_ctx.send(f"Now playing {song_name} from {self.radio_name}")

    def setup_auto_disconnect(self):
        @tasks.loop(minutes=5, loop=self.event_loop)
        async def auto_disconnect():
            voice_client: discord.VoiceClient = self.discord_ctx.voice_client
            members: List[discord.Member] = voice_client.channel.members
            if len([member for member in members if not member.bot]) == 0:
                await self.discord_ctx.send("Disconnecting due to there is nobody in the VC")
                voice_client.stop()
                await voice_client.disconnect()

        auto_disconnect.start()
        self.auto_disconnect: tasks.Loop = auto_disconnect

    def read(self):
        try:
            return audioop.mul(self.audio_queue.get(timeout=15), 2, self._volume)
        except EmptyQueue:
            return b''

    def cleanup(self):
        self.auto_disconnect.cancel()
        self.ffmpeg_process.terminate()

        del self.auto_disconnect
        del self.audio_queue
        del self.ffmpeg_process
        del self.last_now_playing_message

        del self.radio_code_name
        del self.radio_format
        del self.radio_name
        del self.radio_url


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

        radio_data = await self.bot.loop.run_in_executor(None, partial(Radio.get_radio, radio_code_name))

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

    @commands.command(aliases=["radios"])
    async def list_all_radio(self, ctx: commands.Context):
        line_format = "{radio_name} -> {radio_code}\n"
        formatted_str = ""

        radios: Dict = await self.bot.loop.run_in_executor(None, Radio.get_radios)

        radio_code: str
        radio_data: List[str]
        for radio_code, radio_data in radios.items():
            formatted_str += line_format.format(
                radio_name=radio_data[2], radio_code=radio_code)

        await ctx.send(
            "```\n" +
            formatted_str +
            "```"
        )

    @staticmethod
    def get_radio(radio_name: str) -> Union[Dict, bool]:
        with open("data/radios.json", 'r') as json_file:
            radios: Dict = json.load(json_file)

        try:
            return radios[radio_name]
        except:
            return False

    @staticmethod
    def get_radios():
        with open("data/radios.json", 'r') as json_file:
            radios: Dict = json.load(json_file)

        return radios


def setup(bot: commands.Bot):
    bot.add_cog(Radio(bot))
