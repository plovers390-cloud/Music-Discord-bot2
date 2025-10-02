import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Bot configuration
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Updated YouTube DL configuration
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    
    # ADD THESE LINES TO BYPASS BOT DETECTION
    'extract_flat': False,
    'force_ipv4': True,
    'geo_bypass': True,
    'geo_bypass_country': 'US',
    'geo_bypass_ip_block': None,
    
    # Rate limiting to avoid detection
    'ratelimit': 5000000,  # 5 MB/s
    'throttled_rate': 1000000,  # 1 MB/s
    
    # User agent rotation
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    
    # Cookie handling (optional)
    'cookiefile': 'cookies.txt'  # If you have cookies file
}

# SIMPLIFIED FFmpeg options
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.25"',
    'executable': 'ffmpeg'   # 👈 force system FFmpeg
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = self.parse_duration(data.get('duration'))
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            
            if 'entries' in data:
                data = data['entries'][0]
            
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
        except Exception as e:
            print(f"Error extracting info: {e}")
            raise e

    @staticmethod
    def parse_duration(duration):
        if not duration:
            return "Unknown"
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

# Music queue system
class MusicQueue:
    def __init__(self):
        self.queues = {}
    
    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        return self.queues[guild_id]
    
    def clear_queue(self, guild_id):
        if guild_id in self.queues:
            self.queues[guild_id] = []

queue = MusicQueue()

# Stylish embed creator
class MusicEmbeds:
    @staticmethod
    def now_playing(song, requester, position=None, queue_length=0):
        embed = discord.Embed(
            title="🎵 Now Playing",
            color=0x00ffaa,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Title", value=f"```{song.title}```", inline=False)
        embed.add_field(name="Duration", value=f"`{song.duration}`", inline=True)
        embed.add_field(name="Uploader", value=f"`{song.uploader}`", inline=True)
        embed.add_field(name="Requested by", value=requester.mention, inline=True)
        
        if position:
            embed.add_field(name="Position in queue", value=f"`{position}`", inline=True)
        if queue_length > 0:
            embed.add_field(name="Songs in queue", value=f"`{queue_length}`", inline=True)
        
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        
        embed.set_footer(text="Enjoy the music! 🎶")
        return embed

    @staticmethod
    def queue_embed(guild_id):
        queue_list = queue.get_queue(guild_id)
        embed = discord.Embed(
            title="📜 Music Queue",
            color=0xffaa00
        )
        
        if queue_list:
            queue_text = ""
            for i, song in enumerate(queue_list[:10], 1):
                queue_text += f"`{i}.` **{song['title']}** - `{song['duration']}`\n"
            
            if len(queue_list) > 10:
                queue_text += f"\n...and {len(queue_list) - 10} more songs"
            
            embed.add_field(name="Up Next", value=queue_text, inline=False)
        else:
            embed.add_field(name="Up Next", value="Queue is empty", inline=False)
        
        return embed

    @staticmethod
    def error_embed(message):
        embed = discord.Embed(
            title="❌ Error",
            description=message,
            color=0xff0000
        )
        return embed

    @staticmethod
    def success_embed(message):
        embed = discord.Embed(
            title="✅ Success",
            description=message,
            color=0x00ff00
        )
        return embed

# Music bot commands
class MusicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="Play a song from YouTube")
    @app_commands.describe(query="Song name or YouTube URL")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        
        if not interaction.user.voice:
            embed = MusicEmbeds.error_embed("You need to be in a voice channel to play music!")
            await interaction.followup.send(embed=embed)
            return
        
        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client
        
        if voice_client is None:
            voice_client = await voice_channel.connect()
        elif voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)
        
        try:
            # Search for the song
            song = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
            
            guild_queue = queue.get_queue(interaction.guild.id)
            
            if voice_client.is_playing() or voice_client.is_paused():
                guild_queue.append({
                    'title': song.title,
                    'duration': song.duration,
                    'url': query,
                    'requester': interaction.user
                })
                embed = MusicEmbeds.success_embed(
                    f"Added to queue: **{song.title}**\n"
                    f"Position: `{len(guild_queue)}`"
                )
                await interaction.followup.send(embed=embed)
            else:
                # Play immediately
                voice_client.play(song, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(interaction.guild), self.bot.loop))
                
                embed = MusicEmbeds.now_playing(
                    song, 
                    interaction.user,
                    queue_length=len(guild_queue)
                )
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            error_msg = f"Error playing song: {str(e)}"
            print(error_msg)
            embed = MusicEmbeds.error_embed(error_msg)
            await interaction.followup.send(embed=embed)

    async def play_next(self, guild):
        guild_queue = queue.get_queue(guild.id)
        voice_client = guild.voice_client
        
        if not guild_queue or not voice_client:
            return
        
        current_song = guild_queue.pop(0)
        
        try:
            song = await YTDLSource.from_url(current_song['url'], loop=self.bot.loop, stream=True)
            voice_client.play(song, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop))
            
            # Send now playing embed to a text channel
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    embed = MusicEmbeds.now_playing(
                        song, 
                        current_song['requester'],
                        queue_length=len(guild_queue)
                    )
                    await channel.send(embed=embed)
                    break
                
        except Exception as e:
            print(f"Error playing next song: {e}")
            await self.play_next(guild)

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        
        if not voice_client or not voice_client.is_playing():
            embed = MusicEmbeds.error_embed("No music is currently playing!")
            await interaction.response.send_message(embed=embed)
            return
        
        voice_client.stop()
        embed = MusicEmbeds.success_embed("Skipped the current song! ⏭️")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="queue", description="Show the current music queue")
    async def queue(self, interaction: discord.Interaction):
        embed = MusicEmbeds.queue_embed(interaction.guild.id)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="Stop the music and clear the queue")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        
        if not voice_client:
            embed = MusicEmbeds.error_embed("I'm not connected to a voice channel!")
            await interaction.response.send_message(embed=embed)
            return
        
        queue.clear_queue(interaction.guild.id)
        voice_client.stop()
        
        embed = MusicEmbeds.success_embed("Stopped the music and cleared the queue! ⏹️")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pause", description="Pause the current song")
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        
        if not voice_client or not voice_client.is_playing():
            embed = MusicEmbeds.error_embed("No music is currently playing!")
            await interaction.response.send_message(embed=embed)
            return
        
        voice_client.pause()
        embed = MusicEmbeds.success_embed("Paused the music! ⏸️")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="resume", description="Resume the paused song")
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        
        if not voice_client or not voice_client.is_paused():
            embed = MusicEmbeds.error_embed("No music is currently paused!")
            await interaction.response.send_message(embed=embed)
            return
        
        voice_client.resume()
        embed = MusicEmbeds.success_embed("Resumed the music! ▶️")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="disconnect", description="Disconnect the bot from voice channel")
    async def disconnect(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        
        if not voice_client:
            embed = MusicEmbeds.error_embed("I'm not connected to a voice channel!")
            await interaction.response.send_message(embed=embed)
            return
        
        queue.clear_queue(interaction.guild.id)
        await voice_client.disconnect()
        
        embed = MusicEmbeds.success_embed("Disconnected from the voice channel! 👋")
        await interaction.response.send_message(embed=embed)

# Prefix Commands
@bot.command(name='play', aliases=['p'])
async def play_prefix(ctx, *, query):
    """Play a song"""
    if not ctx.author.voice:
        embed = MusicEmbeds.error_embed("You need to be in a voice channel!")
        await ctx.send(embed=embed)
        return
    
    voice_channel = ctx.author.voice.channel
    voice_client = ctx.guild.voice_client
    
    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)
    
    try:
        song = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        
        guild_queue = queue.get_queue(ctx.guild.id)
        
        if voice_client.is_playing() or voice_client.is_paused():
            guild_queue.append({
                'title': song.title,
                'duration': song.duration,
                'url': query,
                'requester': ctx.author
            })
            embed = MusicEmbeds.success_embed(
                f"Added to queue: **{song.title}**\n"
                f"Position: `{len(guild_queue)}`"
            )
            await ctx.send(embed=embed)
        else:
            voice_client.play(song, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx.guild), bot.loop))
            embed = MusicEmbeds.now_playing(song, ctx.author, queue_length=len(guild_queue))
            await ctx.send(embed=embed)
            
    except Exception as e:
        error_msg = f"Error playing song: {str(e)}"
        print(error_msg)
        embed = MusicEmbeds.error_embed(error_msg)
        await ctx.send(embed=embed)

async def play_next(guild):
    guild_queue = queue.get_queue(guild.id)
    voice_client = guild.voice_client
    
    if not guild_queue or not voice_client:
        return
    
    current_song = guild_queue.pop(0)
    
    try:
        song = await YTDLSource.from_url(current_song['url'], loop=bot.loop, stream=True)
        voice_client.play(song, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
        
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                embed = MusicEmbeds.now_playing(
                    song, 
                    current_song['requester'],
                    queue_length=len(guild_queue)
                )
                await channel.send(embed=embed)
                break
                
    except Exception as e:
        print(f"Error playing next song: {e}")
        await play_next(guild)

@bot.command(name='skip', aliases=['s'])
async def skip_prefix(ctx):
    voice_client = ctx.guild.voice_client
    
    if not voice_client or not voice_client.is_playing():
        embed = MusicEmbeds.error_embed("No music is currently playing!")
        await ctx.send(embed=embed)
        return
    
    voice_client.stop()
    embed = MusicEmbeds.success_embed("Skipped the current song! ⏭️")
    await ctx.send(embed=embed)

@bot.command(name='queue', aliases=['q'])
async def queue_prefix(ctx):
    embed = MusicEmbeds.queue_embed(ctx.guild.id)
    await ctx.send(embed=embed)

@bot.command(name='join', aliases=['j'])
async def join_prefix(ctx):
    """Join voice channel"""
    if not ctx.author.voice:
        embed = MusicEmbeds.error_embed("You need to be in a voice channel!")
        await ctx.send(embed=embed)
        return
    
    voice_channel = ctx.author.voice.channel
    voice_client = ctx.guild.voice_client
    
    if voice_client is None:
        await voice_channel.connect()
        embed = MusicEmbeds.success_embed(f"Joined {voice_channel.mention}! 🎵")
        await ctx.send(embed=embed)
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)
        embed = MusicEmbeds.success_embed(f"Moved to {voice_channel.mention}! 🎵")
        await ctx.send(embed=embed)
    else:
        embed = MusicEmbeds.error_embed("I'm already in your voice channel!")
        await ctx.send(embed=embed)

# Autocomplete for song suggestions
async def song_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not current:
        return []
    
    suggestions = [
        "Shape of You - Ed Sheeran",
        "Blinding Lights - The Weeknd",
        "Dance Monkey - Tones and I",
        "Stay - The Kid LAROI, Justin Bieber",
        "Good 4 U - Olivia Rodrigo"
    ]
    
    return [
        app_commands.Choice(name=song, value=song)
        for song in suggestions if current.lower() in song.lower()
    ][:5]

# Add autocomplete to play command
MusicCommands.play.autocomplete("query")(song_autocomplete)

@bot.event
async def on_ready():
    print(f'🤖 {bot.user.name} is online!')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    
    try:
        await bot.add_cog(MusicCommands(bot))
        synced = await bot.tree.sync()
        print(f'✅ Synced {len(synced)} slash commands')
    except Exception as e:
        print(f'❌ Error syncing commands: {e}')

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="your music 🎵"
        )
    )

# Run the bot
try:
    token = os.getenv('DISCORD_TOKEN')
    if token:
        print("✅ Token found, starting bot...")
        bot.run(token)
    else:
        print("❌ ERROR: No token found in .env file")
except Exception as e:

    print(f"❌ Bot failed to start: {e}")
