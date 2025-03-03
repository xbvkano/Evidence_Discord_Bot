import discord
from discord.ext import commands, tasks
import os
import aiohttp
import io
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MARCELO_ID = int(os.getenv("MARCELO_ID"))
RITA_ID = int(os.getenv("RITA_ID"))

# Set your notification interval (e.g., 1 minute)
NOTIFICATION_INTERVAL = timedelta(minutes=1)

# Enable required intents
intents = discord.Intents.default()
intents.message_content = True  # To read message content
intents.messages = True         # To receive message events
intents.guilds = True           # For guild-related events

bot = commands.Bot(command_prefix="!", intents=intents)

# Dictionary to buffer messages per channel (keyed by channel id)
message_buffers = {}

# Dictionary to track pending packages.
# key: package message id
# value: tuple (package_message, creation_time, last_notified_time, target_user_id)
pending_packages = {}

class AppointmentView(discord.ui.View):
    def __init__(
        self,
        original_done_message: discord.Message,
        packaged_text: str,
        source_channel_name: str,
        packaged_attachments: list,
        packaged_messages: list,  # The list of buffered messages (M1, M2, etc.)
        packaging_message: discord.Message = None
    ):
        super().__init__(timeout=None)
        self.original_done_message = original_done_message
        self.packaging_message = packaging_message  # Will be set after sending the package message.
        self.packaged_text = packaged_text
        self.source_channel_name = source_channel_name
        self.packaged_attachments = packaged_attachments  # List of discord.Attachment objects
        self.packaged_messages = packaged_messages  # List of buffered messages (M1, M2, etc.)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, emoji="✅")
    async def done_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("Done button clicked")
        await interaction.response.defer(ephemeral=True)
        # Send a copy to the backlog channel.
        backlog_channel = discord.utils.get(interaction.guild.text_channels, name="backlog")
        files = []
        if backlog_channel:
            embed = discord.Embed(
                title=f"Appointment (from {self.source_channel_name})",
                description=self.packaged_text,
                color=discord.Color.green()
            )
            async with aiohttp.ClientSession() as session:
                for attachment in self.packaged_attachments:
                    try:
                        async with session.get(attachment.url) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                file = discord.File(io.BytesIO(data), filename=attachment.filename)
                                files.append(file)
                            else:
                                print(f"Failed to download {attachment.url} (status {resp.status})")
                    except Exception as e:
                        print(f"Error downloading {attachment.url}: {e}")
            await backlog_channel.send(embed=embed, files=files)
        # Delete all messages used to create the package.
        for msg in self.packaged_messages:
            try:
                await msg.delete()
            except Exception as e:
                print("Failed to delete packaged message:", e)
        try:
            await self.original_done_message.delete()
        except Exception as e:
            print("Failed to delete original done message:", e)
        try:
            await self.packaging_message.delete()
        except Exception as e:
            print("Failed to delete packaging message:", e)
        # Remove package from pending tracking.
        pending_packages.pop(self.packaging_message.id, None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("Cancel button clicked")
        await interaction.response.defer(ephemeral=True)
        for msg in self.packaged_messages:
            try:
                await msg.delete()
            except Exception as e:
                print("Failed to delete packaged message:", e)
        try:
            await self.original_done_message.delete()
        except Exception as e:
            print("Failed to delete original done message:", e)
        try:
            await self.packaging_message.delete()
        except Exception as e:
            print("Failed to delete packaging message:", e)
        pending_packages.pop(self.packaging_message.id, None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_pending_packages.start()  # Start the background task

@bot.event
async def on_message(message: discord.Message):
    # Process only guild text channels (ignore DMs)
    if not isinstance(message.channel, discord.TextChannel):
        return

    # Only process channels named "rita" or "marcelo"
    if message.channel.name.lower() not in ("rita", "marcelo"):
        return

    if message.author.bot:
        return

    if message.channel.id not in message_buffers:
        message_buffers[message.channel.id] = []

    if message.content.strip().lower() == "done":
        buffered_messages = message_buffers[message.channel.id]
        # Copy the buffered messages (M1, M2, etc.) before clearing.
        packaged_messages = buffered_messages.copy()
        packaged_text = ""
        packaged_attachments = []

        for msg in buffered_messages:
            if msg.content:
                packaged_text += f"**{msg.author.display_name}:** {msg.content}\n"
            if msg.attachments:
                for attachment in msg.attachments:
                    packaged_text += f"**{msg.author.display_name} sent an attachment:** {attachment.url}\n"
                    packaged_attachments.append(attachment)
        if message.attachments:
            for attachment in message.attachments:
                packaged_text += f"**{message.author.display_name} sent an attachment with 'done':** {attachment.url}\n"
                packaged_attachments.append(attachment)

        if not packaged_text:
            packaged_text = "No messages to package."

        # Clear the buffer for this channel.
        message_buffers[message.channel.id] = []

        embed = discord.Embed(
            title="Appointment to make",
            description=packaged_text,
            color=discord.Color.blue()
        )

        view = AppointmentView(
            original_done_message=message,
            packaged_text=packaged_text,
            source_channel_name=message.channel.name,
            packaged_attachments=packaged_attachments,
            packaged_messages=packaged_messages
        )
        packaging_message = await message.channel.send(embed=embed, view=view)
        view.packaging_message = packaging_message

        # Track package based on channel.
        now = datetime.utcnow()
        if message.channel.name.lower() == "marcelo":
            pending_packages[packaging_message.id] = (packaging_message, now, now, MARCELO_ID)
        elif message.channel.name.lower() == "rita":
            pending_packages[packaging_message.id] = (packaging_message, now, now, RITA_ID)
    else:
        message_buffers[message.channel.id].append(message)

    await bot.process_commands(message)

@tasks.loop(seconds=10)
async def check_pending_packages():
    now = datetime.utcnow()
    for pkg_id, (pkg_message, creation_time, last_notified, target_user_id) in list(pending_packages.items()):
        print(f"Checking package {pkg_id}, time since creation: {now - last_notified}")
        if now - last_notified >= NOTIFICATION_INTERVAL:
            try:
                user = await bot.fetch_user(target_user_id)
                if user:
                    print(f"Sending DM to {user.display_name} for package {pkg_id}")
                    await user.send(
                        f"A package in the {pkg_message.channel.name} channel (ID: {pkg_id}) has been pending for {now - creation_time}."
                    )
                # Update last notified time.
                pending_packages[pkg_id] = (pkg_message, creation_time, now, target_user_id)
            except Exception as e:
                print("Failed to send DM to target user:", e)

bot.run(DISCORD_BOT_TOKEN)
