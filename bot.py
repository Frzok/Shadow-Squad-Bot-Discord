import discord
from discord.ext import commands, tasks
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta
import config
import random

# Load environment variables
load_dotenv()

# Define bot intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.messages = True

# Initialize the bot
bot = commands.Bot(command_prefix="!", intents=intents)

# State tracking dictionaries
empty_channels = {}
created_channels = set()
guest_role_timers = {}
user_channel_count = {}
last_pidor_check = None
pidor_of_the_day = None  # Инициализация глобальной переменной
pidor_stats = {}  # Dictionary to store pidor_of_the_day statistics

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    await bot.tree.sync()
    check_empty_channels.start()
    check_guest_roles.start()
    send_weekly_messages.start()
    reset_weekly_stats.start()

@bot.event
async def on_member_join(member):
    guest_role = member.guild.get_role(config.GUEST_ROLE_ID)
    if guest_role:
        await member.add_roles(guest_role)
        guest_role_timers[member.id] = datetime.now()
        print(f"Assigned 'Гость' role to {member.name}")

@tasks.loop(hours=24)
async def check_guest_roles():
    current_time = datetime.now()
    guild = bot.get_guild(config.GUILD_ID)
    guest_role = guild.get_role(config.GUEST_ROLE_ID)

    expired_members = [
        member_id for member_id, assign_time in guest_role_timers.items()
        if current_time - assign_time >= timedelta(days=config.GUEST_ROLE_DURATION)
    ]

    for member_id in expired_members:
        member = guild.get_member(member_id)
        if member and guest_role:
            await member.remove_roles(guest_role)
            print(f"Removed 'Гость' role from {member.name}")
        guest_role_timers.pop(member_id, None)

@tasks.loop(minutes=1)
async def check_empty_channels():
    current_time = asyncio.get_event_loop().time()
    guild = bot.get_guild(config.GUILD_ID)

    to_delete = [
        channel_id for channel_id, timestamp in empty_channels.items()
        if current_time - timestamp >= config.EMPTY_CHANNEL_DURATION and channel_id in created_channels
    ]

    for channel_id in to_delete:
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.delete()
            print(f"Deleted empty channel {channel.name}")
        empty_channels.pop(channel_id, None)
        created_channels.discard(channel_id)

@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    if after.channel and after.channel.id in config.TARGET_CHANNEL_IDS:
        if before.channel is None or before.channel.id not in config.TARGET_CHANNEL_IDS:
            if user_channel_count.get(member.id, 0) < config.MAX_CHANNELS_PER_USER:
                category = discord.utils.get(guild.categories, id=config.TEMP_CHANNEL_CATEGORY_ID)
                if category:
                    new_channel_name = f"{after.channel.name} {user_channel_count.get(member.id, 0) + 1}"
                    new_channel = await guild.create_voice_channel(new_channel_name, category=category)
                    await new_channel.edit(user_limit=config.MAX_USERS_PER_TEMP_CHANNEL)
                    await member.move_to(new_channel)
                    user_channel_count[member.id] = user_channel_count.get(member.id, 0) + 1
                    created_channels.add(new_channel.id)
                    print(f"Created new channel {new_channel.name} and moved {member.name} to it")

    if before.channel and len(before.channel.members) == 0:
        empty_channels[before.channel.id] = asyncio.get_event_loop().time()

    if after.channel and after.channel.id in empty_channels:
        empty_channels.pop(after.channel.id, None)

@tasks.loop(minutes=1)
async def send_weekly_messages():
    now = datetime.now()
    target_time = now.replace(hour=20, minute=30, second=0, microsecond=0)

    if now.weekday() in [4, 6] and target_time <= now < target_time + timedelta(minutes=1):
        channel = bot.get_channel(config.CHANNEL_ID)
        if channel:
            message = f"<@&{config.ROLE_ID}> РТ Старт Сбор + в ПМ <@{config.USER_ID}>"
            await channel.send(message)
            print(f"Sent scheduled message to {channel.name} at {now.strftime('%Y-%m-%d %H:%M:%S')}")

@bot.tree.command(name="pidor_of_the_day", description="Choose the pidor of the day")
async def pidor_of_the_day(interaction: discord.Interaction):
    global last_pidor_check, pidor_of_the_day

    now = datetime.now()

    if last_pidor_check is None or last_pidor_check.date() != now.date():
        guild = interaction.guild
        roles_to_choose_from = [
            guild.get_role(config.ROLE_IDS["SERGEANT"]),
            guild.get_role(config.ROLE_IDS["OCHKO"]),
            guild.get_role(config.ROLE_IDS["RL"])
        ]

        eligible_members = [member for role in roles_to_choose_from if role for member in role.members]

        if eligible_members:
            pidor_of_the_day = random.choice(eligible_members)
            last_pidor_check = now

            # Обновление статистики
            pidor_stats[pidor_of_the_day.id] = pidor_stats.get(pidor_of_the_day.id, 0) + 1

            # Отправка начальных сообщений
            msg1 = await interaction.channel.send("Что тут у нас?")
            await asyncio.sleep(5)
            msg2 = await interaction.channel.send("А могли бы на работе делом заниматься...")
            await asyncio.sleep(5)
            msg3 = await interaction.channel.send("Проверяю данные...")
            await asyncio.sleep(5)

            # Отправка финального сообщения с упоминанием пользователя
            await interaction.channel.send(f"ВЖУХ И ТЫ ПИДОР: {pidor_of_the_day.mention}")
            print(f"Selected {pidor_of_the_day.display_name} as the pidor of the day.")

            # Удаление первых трёх сообщений после отправки финального сообщения
            await msg1.delete()
            await msg2.delete()
            await msg3.delete()
        else:
            await interaction.channel.send(config.MESSAGES["NO_CANDIDATES"])
            print("No eligible members found for the pidor selection.")
    else:
        # При повторе выводим только финальное сообщение
        await interaction.channel.send(f"ВЖУХ И ТЫ ПИДОР: {pidor_of_the_day.mention}")
        print(f"Repeated pidor of the day: {pidor_of_the_day.display_name}")

@bot.tree.command(name="pidors_of_the_week", description="Show the pidor of the week statistics")
async def pidors_of_the_week(interaction: discord.Interaction):
    await interaction.response.defer()  # Отложить ответ, чтобы избежать таймаута

    if not pidor_stats:
        await interaction.followup.send(config.MESSAGES["NO_PIDORS"])
        return

    message = config.MESSAGES["PIDORS_OF_THE_WEEK"]
    for user_id, count in pidor_stats.items():
        user = interaction.guild.get_member(user_id)
        if user:  # Убедитесь, что пользователь существует
            message += f"{user.display_name}: {count} раз(а)\n"
        else:
            message += f"Пользователь с ID {user_id} не найден: {count} раз(а)\n"

    await interaction.followup.send(message)

@tasks.loop(hours=168)  # 168 hours = 1 week
async def reset_weekly_stats():
    global pidor_stats
    pidor_stats.clear()
    print("Pidor statistics have been reset for the new week.")

@bot.event
async def on_message(message):
    if message.author.id == config.USER_ID_TO_DELETE:
        await asyncio.sleep(10)
        await message.delete()
        print(f"Deleted message from {message.author.name}: {message.content}")

    await bot.process_commands(message)

@bot.event
async def on_member_update(before, after):
    role_id = config.ROLE_IDS["SERGEANT"]
    role = discord.utils.get(after.guild.roles, id=role_id)

    if role in after.roles and role not in before.roles:
        message = config.MESSAGES["WELCOME_MESSAGE"]

        try:
            await after.send(message)
            print(f"Sent a welcome message to {after.name}.")
        except discord.Forbidden:
            print(f"Cannot send message to {after.name}. They have disabled DMs.")
        except discord.HTTPException as e:
            print(f"Failed to send message to {after.name}: {e}")

async def main():
    try:
        await bot.start(config.DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        print("Bot is shutting down gracefully...")
    except Exception as main_error:
        print(f"An unexpected error occurred: {main_error}")
    finally:
        await bot.close()

# Run the main function
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted manually.")
    except Exception as run_error:
        print(f"An unexpected error occurred during asyncio execution: {run_error}")
