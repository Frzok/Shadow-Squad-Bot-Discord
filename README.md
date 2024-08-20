# Shadow-Squad-Bot-Discord README
Overview
This bot is designed to manage various tasks within a Discord server, including channel management, role assignments, and special features like the "Pidor of the Day" game. The bot is built using the discord.py library and is intended to automate server management tasks and provide some fun interactions for the members.

Features
1. Automatic Role Assignment
Guest Role Assignment: New members are automatically assigned the "Guest" role upon joining the server.
Role Duration Management: The bot periodically checks and removes the "Guest" role from members who have exceeded the designated time limit.
2. Voice Channel Management
Temporary Voice Channels: When a user joins a specified voice channel, the bot creates a temporary voice channel for them, with limits on the number of channels a user can create.
Empty Channel Cleanup: The bot monitors temporary voice channels and deletes them if they remain empty for a certain period.
3. Scheduled Messaging
Weekly Reminders: The bot sends scheduled messages to specific channels on designated days (e.g., Fridays and Sundays at 20:30).
4. "Pidor of the Day" Game
Daily Selection: The bot randomly selects a "Pidor of the Day" from eligible members with certain roles.
Statistics Tracking: The bot keeps track of how many times each member has been chosen as the "Pidor of the Day" and resets the stats weekly.
5. Message Deletion
Targeted Deletion: Automatically deletes messages from a specific user after a short delay.
6. Member Updates
Role-based Welcome Messages: Sends a welcome message via DM when a member receives a specific role (e.g., "Sergeant").
Setup
Prerequisites
Python 3.8 or later.
discord.py library.
python-dotenv for loading environment variables.
Configuration
Environment Variables: Create a .env file to store sensitive information like the bot token.

makefile
Копировать код
DISCORD_BOT_TOKEN=your_bot_token_here
Configuration File (config.py):

GUILD_ID: The ID of the server where the bot operates.
GUEST_ROLE_ID: Role ID for the "Guest" role.
GUEST_ROLE_DURATION: Duration (in days) for which a user should keep the "Guest" role.
TARGET_CHANNEL_IDS: List of channel IDs where the bot should create temporary voice channels.
TEMP_CHANNEL_CATEGORY_ID: Category ID where temporary voice channels are created.
MAX_CHANNELS_PER_USER: Maximum number of temporary channels a user can create.
MAX_USERS_PER_TEMP_CHANNEL: Maximum number of users allowed in a temporary channel.
CHANNEL_ID: Channel ID where scheduled messages are sent.
ROLE_ID: Role ID to mention in scheduled messages.
USER_ID: User ID to mention in scheduled messages.
ROLE_IDS: Dictionary containing role IDs for "Sergeant", "Ochko", and "RL".
MESSAGES: Dictionary containing custom messages for different bot actions.
Running the Bot
Ensure all dependencies are installed:

bash
Копировать код
pip install discord.py python-dotenv
Start the bot by running the Python script:

bash
Копировать код
python your_script_name.py
Usage
Pidor of the Day: Use the /pidor_of_the_day command to randomly select a "Pidor of the Day".
Weekly Pidor Stats: Use the /pidors_of_the_week command to display the weekly statistics of the "Pidor of the Day" game.
Error Handling
The bot includes basic error handling to log unexpected errors and handle Discord-specific exceptions like message deletion restrictions and failed DMs.
Contributing
To contribute to this project, please fork the repository and submit a pull request. Ensure your code follows the project's coding standards and is well-documented.

License
This project is licensed under the MIT License. See the LICENSE file for details.
