"""
Embed Utilities
Helper functions for creating embeds
"""

import discord
from datetime import datetime, timezone

def create_progress_bar(current: int, target: int, length: int = 10) -> str:
    """
    Create a visual progress bar
    
    Args:
        current: Current value
        target: Target value
        length: Length of progress bar (default 10)
    
    Returns:
        str: Progress bar string (e.g., "🟩🟩🟩⬜⬜⬜⬜⬜⬜⬜")
    """
    if target <= 0:
        return "⬜" * length
    
    progress_pct = min(100, int((current / target) * 100))
    filled = int((progress_pct / 100) * length)
    empty = length - filled
    
    return "🟩" * filled + "⬜" * empty

def create_stats_embed(title: str, description: str, stats: dict, color=discord.Color.blue()) -> discord.Embed:
    """
    Create a standardized stats embed
    
    Args:
        title: Embed title
        description: Embed description
        stats: Dictionary of stat name -> value
        color: Embed color
    
    Returns:
        discord.Embed: Configured embed
    """
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    
    for name, value in stats.items():
        embed.add_field(
            name=name,
            value=str(value),
            inline=True
        )
    
    return embed

def create_leaderboard_embed(title: str, leaderboard_data: list, emoji: str = "🏆") -> discord.Embed:
    """
    Create a leaderboard embed
    
    Args:
        title: Embed title
        leaderboard_data: List of (name, score) tuples
        emoji: Emoji to use in title
    
    Returns:
        discord.Embed: Configured leaderboard embed
    """
    embed = discord.Embed(
        title=f"{emoji} {title}",
        description="Top performers",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )
    
    medals = ['🥇', '🥈', '🥉']
    leaderboard_text = []
    
    for i, (name, score) in enumerate(leaderboard_data[:10], 1):
        if i <= 3:
            prefix = medals[i-1]
        else:
            prefix = f"`{i}.`"
        
        leaderboard_text.append(f"{prefix} **{name}** - {score}")
    
    if leaderboard_text:
        embed.add_field(
            name="Rankings",
            value="\n".join(leaderboard_text),
            inline=False
        )
    else:
        embed.add_field(
            name="No Data",
            value="No rankings available",
            inline=False
        )
    
    return embed