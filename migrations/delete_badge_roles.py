"""
One-time script to delete the 5 Power Points badge roles from Staff Hub guild.
Run with: python migrations/delete_badge_roles.py

Uses the bot token from .env to connect to Discord and delete the roles.
"""
import os
import sys
import asyncio
import discord
from dotenv import load_dotenv

load_dotenv(override=True)

STAFF_HUB_GUILD_ID = 1041450125391835186

BADGE_ROLE_IDS = {
    'God':    1508413031024169122,
    'Legend': 1508412963718168687,
    'Gold':   1508412960584765441,
    'Silver': 1508412940489982022,
    'Bronze': 1508412912715436133,
}


async def main():
    token = os.getenv('DISCORD_TOKEN') or os.getenv('BOT_TOKEN')
    if not token:
        print("ERROR: No bot token found in .env (DISCORD_TOKEN or BOT_TOKEN)")
        sys.exit(1)

    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"Connected as {client.user}")
        guild = client.get_guild(STAFF_HUB_GUILD_ID)
        if not guild:
            print(f"ERROR: Could not find guild {STAFF_HUB_GUILD_ID}")
            await client.close()
            return

        print(f"Guild: {guild.name}")
        deleted = 0
        for name, role_id in BADGE_ROLE_IDS.items():
            role = guild.get_role(role_id)
            if role:
                member_count = len(role.members)
                print(f"  Deleting '{role.name}' (ID {role_id}, {member_count} members)...")
                try:
                    await role.delete(reason="Power Points system retired — Lifetime Stats Consolidation")
                    print(f"  ✅ Deleted '{name}' role")
                    deleted += 1
                except discord.Forbidden:
                    print(f"  ❌ Missing permissions to delete '{name}' role")
                except Exception as e:
                    print(f"  ❌ Error deleting '{name}' role: {e}")
            else:
                print(f"  ⚠️ '{name}' role (ID {role_id}) not found — already deleted?")

        print(f"\nDone: {deleted}/{len(BADGE_ROLE_IDS)} roles deleted")
        await client.close()

    await client.start(token)


if __name__ == '__main__':
    asyncio.run(main())
