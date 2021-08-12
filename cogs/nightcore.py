import time
import audioop
import youtube_dl
import discord
import asyncio
import subprocess
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import Lock
from types import GeneratorType
from typing import *
from dataclasses import dataclass, field
from discord.ext import commands, tasks

@dataclass
class SongFileInfo:
    """Class for Song File Info"""
    filename: str
    title: str = field(compare=False)
    duration: int = field(compare=False)

    def __post_init__(self):
        self.nightcore_duration: int = int(self.duration / 1.3)

    @property
    def duration_nightcore_string(self):
        return f"{self.nightcore_duration // 60}:{str(self.nightcore_duration % 60).zfill(2)}"


class NightcorePlayer(discord.AudioSource):

    def __init__(self, video_link: str, discord_ctx: commands.Context, pool: ThreadPoolExecutor):
        self.lock = Lock()
        self.pool = pool

        self.playlist: List[SongFileInfo] = []
        self.currently_playing_index = -1

        self.ffmpeg: subprocess.Popen = None

        self.discord_ctx = discord_ctx
        self.event_loop: asyncio.AbstractEventLoop = discord_ctx.bot.loop

        self.repeating_mode = False

        self.add_song(video_link)

        self.audio_reader = self.audio_generator_nc()

        self.setup_auto_disconnect()


    def add_song(self, video_link: str):
        self.lock.acquire()
        try:
            try:
                extracted_info = youtube_dl.YoutubeDL(params={"noplaylist": True, "quiet": True}).extract_info(video_link, process=False)
            except youtube_dl.utils.DownloadError:
                self.event_loop.create_task(self.discord_ctx.send("Sorry, searching youtube is not supported or your link is invalid"))
                return
            extractor = extracted_info.get("extractor")

            if "youtube" in extractor:
                ydl_config = {
                    "outtmpl": "./media/%(id)s.%(ext)s",
                    "format": "250/251",
                    "quiet": True,
                    "noplaylist": True
                }
                info_type = extracted_info.get("_type", "video")

                if info_type == "video":
                    with youtube_dl.YoutubeDL(params=ydl_config) as ydl:
                        try:
                            processed_ie = ydl.process_ie_result(extracted_info, download=True)
                        except (youtube_dl.utils.ExtractorError, youtube_dl.utils.DownloadError):
                            # if we reached here, it means that the link might be a livestream
                            self.event_loop.create_task(self.discord_ctx.send("Link is unsupported..."))
                            return
                        filename = ydl.prepare_filename(processed_ie)
                elif info_type == "url" and extracted_info.get("webpage_url_basename") == "watch":
                    with youtube_dl.YoutubeDL(params=ydl_config) as ydl:
                        try:
                            processed_ie = ydl.extract_info(extracted_info.get("url"), ie_key=extracted_info.get("ie_key"))
                        except youtube_dl.utils.DownloadError:
                            self.event_loop.create_task(self.discord_ctx.send("Error downloading this -->" + extracted_info.get("url")))
                            return
                        filename = ydl.prepare_filename(processed_ie)
                elif info_type == "playlist":
                    entries = extracted_info.get("entries")
                    if isinstance(entries, GeneratorType):
                        first_entry = next(entries)
                        with youtube_dl.YoutubeDL(params=ydl_config) as ydl:
                            try:
                                processed_ie = ydl.extract_info(first_entry.get("url"), ie_key=first_entry.get("ie_key"))
                            except youtube_dl.utils.DownloadError:
                                self.event_loop.create_task(self.discord_ctx.send("Error downloading this -->" + first_entry.get("url")))
                                return
                            filename = ydl.prepare_filename(processed_ie)
                        

                
                song_file_info = SongFileInfo(filename, processed_ie.get("title"), processed_ie.get("duration"))

                if song_file_info not in self.playlist:
                    self.playlist.append(song_file_info)
                
                if info_type == "playlist":
                    later_entries = list(entries)
                    self.event_loop.create_task(self.discord_ctx.send(f"Queuing {len(later_entries) + 1} songs."))
                    self.pool.submit(self.process_playlist_youtube, later_entries)
                else:
                    self.event_loop.create_task(self.discord_ctx.send(f"Queued `{song_file_info.title}` - {song_file_info.duration_nightcore_string}"))
                
            else:
                self.event_loop.create_task(self.discord_ctx.send("Link is unsupported for now come back later!"))
                return
        finally:
            try:
                self.lock.release()
            except RuntimeError:
                # we reached here because we tried to release an unlocked lock.
                pass

    def audio_generator_nc(self):
        while True:
            self.currently_playing_index += 1

            if self.playlist and len(self.playlist) >= self.currently_playing_index + 1:
                current_song_file = self.playlist[self.currently_playing_index]
            elif self.repeating_mode:
                self.currently_playing_index = -1
                continue
            else:
                if self.lock.locked():
                    self.lock.acquire()
                    self.lock.release()
                    continue
                break

            self.event_loop.create_task(self.discord_ctx.send(f"Currently playing `{self.currently_playing_index + 1}. {current_song_file.title}` - {current_song_file.duration_nightcore_string}"))

            self.ffmpeg = subprocess.Popen(f"ffmpeg -i {current_song_file.filename} -f s16le -ac 2 -ar 48000 -filter_complex rubberband=tempo=1.3:pitch=1.3,bass=gain=2,treble=gain=-1 -".split(), stdout=subprocess.PIPE, stdin=subprocess.PIPE, creationflags=0x08000000)

            while True:
                # 3840 is the amount of byte that has 20ms amount of audio
                try:
                    audio_frame = self.ffmpeg.stdout.read(3840)
                except ValueError:
                    # read of closed file
                    break
                if audio_frame:
                    yield audio_frame
                else:
                    break
    
    def queue(self):
        queue_string = "```\n"
        try:
            for index in range(len(self.playlist)):
                a_song_file = self.playlist[index]
                if index == self.currently_playing_index:
                    queue_string += f"{index + 1}. {a_song_file.title} - {a_song_file.duration_nightcore_string} <--- Now playing\n"
                else:
                    queue_string += f"{index + 1}. {a_song_file.title} - {a_song_file.duration_nightcore_string}\n"
        except AttributeError:
            return "```\n```"
        
        return queue_string + "```"


    def process_playlist_youtube(self, ie_entries: List):
        ydl_config = {
            "outtmpl": "./media/%(id)s.%(ext)s",
            "format": "250/251",
            "quiet": True,
            "noplaylist": True
        }
        ydl = youtube_dl.YoutubeDL(params=ydl_config)
        for ie_entry in ie_entries:
            time.sleep(0.083)
            self.lock.acquire()
            try:
                try:
                    processed_ie = ydl.extract_info(ie_entry.get("url"), ie_key=ie_entry.get("ie_key"))
                except youtube_dl.utils.DownloadError:
                    self.event_loop.create_task(self.discord_ctx.send("Error downloading this -->" + ie_entry.get("url")))
                    
                
                filename = ydl.prepare_filename(processed_ie)

                song_file_info = SongFileInfo(filename, processed_ie.get("title"), processed_ie.get("duration"))

                if song_file_info not in self.playlist:
                    try:
                        self.playlist.append(song_file_info)
                    except (NameError, Exception) as e:
                        print(e)
                        return
            finally:
                self.lock.release()


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

    def skip(self, index: int):
        if index > -1:
            self.currently_playing_index = index - 1
        self.ffmpeg.communicate(b'q')

    def read(self):
        if isinstance(self.audio_reader, GeneratorType):
            try:
                audio_frame = next(self.audio_reader)
            except StopIteration:
                return b''
            if len(audio_frame) < 3840:
                return bytes(3840)
            else:
                return audioop.mul(audio_frame, 2, 0.07)
        else:
            return b''
    
    def cleanup(self):
        try:
            self.ffmpeg.terminate()
        except AttributeError:
            # this mean that ffmpeg is already terminated naturally
            pass
        del self.playlist
            

class Nightcore(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool = ThreadPoolExecutor()

    @commands.Cog.listener()
    async def on_ready(self):
        print("Nightcore Cog is loaded.")
    
    @commands.command(aliases=["nc"])
    async def nightcore(self, ctx: commands.Context, video_link: str):
        # await ctx.send("Nightcore feature coming soon!")

        if ctx.voice_client.is_playing():
            source: NightcorePlayer = ctx.voice_client.source
            async with ctx.typing():
                await self.bot.loop.run_in_executor(None, partial(source.add_song, video_link))
            return

        async with ctx.typing():
            player = await self.bot.loop.run_in_executor(None, partial(NightcorePlayer, video_link, ctx, self.pool))

        ctx.voice_client.play(player)

    @nightcore.before_invoke
    async def nightcore_before_invoke(self, ctx: commands.Context):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
                print(f"Connected to the {ctx.author}'s voice channel on {ctx.guild} server!")
                # TODO: use logging
            else:
                await ctx.send("Please join a VC first!")
                raise discord.CommandError(f"{ctx.author} tried to summon bot while being outside of VC.")
        elif ctx.voice_client.is_playing() and not isinstance(ctx.voice_client.source, NightcorePlayer):
            ctx.voice_client.stop()
    
    @commands.command(aliases=["queue"])
    async def nc_queue(self, ctx: commands.Context):
        if ctx.voice_client is not None and isinstance(ctx.voice_client.source, NightcorePlayer):
            await ctx.send(await self.bot.loop.run_in_executor(None, ctx.voice_client.source.queue))
        else:
            await ctx.send("Can't show queue right now...")
    
    @commands.command(aliases=["skip"])
    async def nc_skip(self, ctx: commands.Context, index: int = 0):
        """Index start from 1"""
        if ctx.voice_client is not None and isinstance(ctx.voice_client.source, NightcorePlayer):
            source: NightcorePlayer = ctx.voice_client.source
            await self.bot.loop.run_in_executor(None, partial(source.skip, index - 1))
        else:
            await ctx.send("Can't skip!")
    
    @commands.command(aliases=["repeat"])
    async def nc_repeat(self, ctx: commands.Context):
        if ctx.voice_client is not None and isinstance(ctx.voice_client.source, NightcorePlayer):
            source: NightcorePlayer = ctx.voice_client.source
            source.repeating_mode = not source.repeating_mode
            if source.repeating_mode:
                await ctx.send("Turned repeating mode on!")
            else:
                await ctx.send("Turned repeating mode off!")
        else:
            await ctx.send("Can't repeat right now...")


def setup(bot: commands.Bot):
    bot.add_cog(Nightcore(bot))
