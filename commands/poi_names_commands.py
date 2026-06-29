import discord
from discord.ext import commands
import aiohttp
import logging

logger = logging.getLogger('discord')

class POINamesCommands(commands.Cog):
    """Commands for retrieving Fortnite POIs and Landmarks."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='landmarks')
    async def landmarks(self, ctx):
        """Fetches and displays the list of current Fortnite landmarks (unnamed POIs)."""
        await ctx.typing()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://fortnite-api.com/v1/map") as response:
                    if response.status != 200:
                        await ctx.send(f"❌ Failed to fetch map data. API returned status {response.status}")
                        return
                    
                    data = await response.json()
            
            pois = data.get('data', {}).get('pois', [])
            landmarks_list = []
            
            # Keep track of counts so duplicates get marked as (2), (3), etc.
            name_counts = {}
            
            for p in pois:
                if 'id' in p and 'UnNamedPOI' in p['id']:
                    name = p.get('name')
                    if name:
                        name_counts[name] = name_counts.get(name, 0) + 1
                        count = name_counts[name]
                        if count == 1:
                            landmarks_list.append(name)
                        else:
                            landmarks_list.append(f"{name} ({count})")
                        
            if not landmarks_list:
                await ctx.send("No landmarks found.")
                return
                
            # Format nicely as bullet points
            landmarks_text = "\n".join(f"• {name}" for name in landmarks_list)
            
            # Ensure it fits within embed description limit (4096)
            if len(landmarks_text) > 4000:
                landmarks_text = landmarks_text[:3990] + "...\n*(List truncated)*"
                
            embed = discord.Embed(
                title="🗺️ Current Fortnite Landmarks",
                description=landmarks_text,
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Total Landmarks: {len(landmarks_list)} | Source: fortnite-api.com")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"[POINames] Error fetching landmarks: {e}")
            await ctx.send("❌ An error occurred while fetching landmarks.")

    @commands.command(name='namedlocations', aliases=['namedpois', 'locations'])
    async def named_locations(self, ctx):
        """Fetches and displays the list of current Fortnite named locations."""
        await ctx.typing()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://fortnite-api.com/v1/map") as response:
                    if response.status != 200:
                        await ctx.send(f"❌ Failed to fetch map data. API returned status {response.status}")
                        return
                    
                    data = await response.json()
            
            pois = data.get('data', {}).get('pois', [])
            named_list = []
            
            # Keep track of counts so duplicates get marked as (2), (3), etc.
            name_counts = {}
            
            for p in pois:
                if 'id' in p and 'UnNamedPOI' not in p['id']:
                    name = p.get('name')
                    if name:
                        name_counts[name] = name_counts.get(name, 0) + 1
                        count = name_counts[name]
                        if count == 1:
                            named_list.append(name)
                        else:
                            named_list.append(f"{name} ({count})")
                        
            if not named_list:
                await ctx.send("No named locations found.")
                return
                
            # Format nicely as bullet points
            named_text = "\n".join(f"• {name}" for name in named_list)
            
            # Ensure it fits within embed description limit (4096)
            if len(named_text) > 4000:
                named_text = named_text[:3990] + "...\n*(List truncated)*"
                
            embed = discord.Embed(
                title="🏙️ Current Fortnite Named Locations",
                description=named_text,
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Total Named Locations: {len(named_list)} | Source: fortnite-api.com")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"[POINames] Error fetching named locations: {e}")
            await ctx.send("❌ An error occurred while fetching named locations.")

async def setup(bot):
    await bot.add_cog(POINamesCommands(bot))
    logger.info("✅ POINamesCommands cog loaded")
