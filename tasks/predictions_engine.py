"""
Shared predictions engine — single source of truth for placing bets, resolving,
and cancelling predictions. Used by BOTH the Discord commands and the website
queue processor so the Wave Points math lives in exactly one place.

Economics (parimutuel — matches the "winners split ENTIRE pool proportionally"
rule): each bet is validated against the user's WP balance. On resolve, every
voter's stake is deducted and the winners split the entire pool in proportion to
their stake. If nobody picked the winning outcome the pool is voided (no
deductions made, since stakes are not pre-reserved for WP).
"""
import logging

import database
from tasks.wave_points import add_wave_points, get_wave_points

logger = logging.getLogger('discord')

MIN_BET = 10


async def place_web_vote(bot, prediction_id: int, user_id: int, choice: str, amount: int) -> dict:
    """Validate + reserve a bet. amount is the NEW TOTAL stake for this user on
    this prediction (matching the bot command: you can raise, not lower/change).
    Returns {'success': bool, 'message': str, 'reserved': int}."""
    prediction = await database.get_prediction_db(prediction_id)
    if not prediction:
        return {'success': False, 'message': 'Prediction not found.'}
    if prediction['status'] != 'active':
        return {'success': False, 'message': 'This prediction is closed.'}

    valid = [o.lower() for o in prediction['outcomes']]
    choice = choice.lower().strip()
    if choice not in valid:
        return {'success': False, 'message': f"Invalid choice. Options: {', '.join(prediction['outcomes'])}"}

    if amount < MIN_BET:
        return {'success': False, 'message': f'Minimum prediction is {MIN_BET} Wave Points.'}

    # Existing vote (if any) — enforce same-choice + raise-only.
    votes = await database.get_votes_db(prediction_id)
    existing = votes.get(user_id) or votes.get(str(user_id))
    prev_amount = 0
    if existing:
        prev_amount = int(existing['amount'])
        if existing['choice'].lower() != choice:
            return {'success': False,
                    'message': f"You already predicted on **{existing['choice'].upper()}** — you can't change your choice, only raise."}
        if amount < prev_amount:
            return {'success': False, 'message': f'You can only raise your prediction (currently {prev_amount}).'}

    delta = amount - prev_amount
    if delta <= 0:
        return {'success': False, 'message': 'No change to your prediction.'}

    available_wp = await get_wave_points(user_id)
    if available_wp < delta:
        return {'success': False,
                'message': f'Not enough Wave Points. Need {delta} more, have {available_wp}.'}

    # Record the (new total) vote — WP are deducted only on resolve.
    await database.place_vote_db(prediction_id, user_id, choice, amount, {})
    logger.info(f"[Predictions] User {user_id} bet {amount} (Δ{delta}) on '{choice}' for #{prediction_id}")
    return {'success': True, 'message': f'Prediction placed: {amount} Wave Points on {choice.upper()}.', 'reserved': amount}


async def resolve_prediction(bot, prediction_id: int, winning_choice: str) -> dict:
    """Settle a prediction: consume all stakes, pay winners their share of the
    whole pool. Returns a summary dict (also used to build embeds/DMs)."""
    prediction = await database.get_prediction_db(prediction_id)
    if not prediction:
        return {'success': False, 'message': 'Prediction not found.'}
    if prediction['status'] not in ('active', 'voting_closed'):
        return {'success': False, 'message': 'Prediction already settled.'}

    winning_choice = winning_choice.lower().strip()
    valid = [o.lower() for o in prediction['outcomes']]
    if winning_choice not in valid:
        return {'success': False, 'message': f"Invalid outcome. Options: {', '.join(prediction['outcomes'])}"}

    votes = await database.get_votes_db(prediction_id)
    winners, losers = [], []
    for uid, vd in votes.items():
        uid = int(uid)
        entry = (uid, int(vd['amount']))
        if vd['choice'].lower() == winning_choice:
            winners.append(entry)
        else:
            losers.append(entry)

    total_pool = sum(a for _, a in winners) + sum(a for _, a in losers)
    total_winner_stake = sum(a for _, a in winners)

    await database.update_prediction_status_db(prediction_id, 'ended', winning_choice)

    payouts = []
    if not winners:
        # Nobody won — void: no WP were pre-deducted, so nothing to refund.
        logger.info(f"[Predictions] #{prediction_id} voided (no winners) — {len(losers)} stakes returned (no WP taken)")
        return {'success': True, 'voided': True, 'winning_choice': winning_choice,
                'total_pool': total_pool, 'winners': [], 'losers': [],
                'title': prediction['title'], 'message': 'No winners — all stakes returned.'}

    # Deduct every stake, then pay winners their proportional share of the pool.
    for uid, amount in winners + losers:
        await add_wave_points(uid, -amount, reason="Prediction wager")

    for uid, amount in winners:
        winnings = int(total_pool * (amount / total_winner_stake)) if total_winner_stake else 0
        await add_wave_points(uid, winnings, reason="Prediction winnings")
        payouts.append({'user_id': uid, 'stake': amount, 'winnings': winnings,
                        'proportion': (amount / total_winner_stake) if total_winner_stake else 0})

    await _dm_winners(bot, prediction, winning_choice, payouts)
    logger.info(f"[Predictions] #{prediction_id} resolved → {winning_choice}; pool {total_pool}, {len(winners)} winners")
    return {'success': True, 'voided': False, 'winning_choice': winning_choice,
            'total_pool': total_pool, 'winners': payouts, 'losers': losers,
            'title': prediction['title'],
            'message': f'Resolved: {winning_choice.upper()} — pool {total_pool} WP split across {len(winners)} winner(s).'}


async def cancel_prediction(bot, prediction_id: int) -> dict:
    """Cancel a prediction and refund every stake (release reservations only)."""
    prediction = await database.get_prediction_db(prediction_id)
    if not prediction:
        return {'success': False, 'message': 'Prediction not found.'}
    if prediction['status'] not in ('active', 'voting_closed'):
        return {'success': False, 'message': 'Prediction already settled.'}

    votes = await database.get_votes_db(prediction_id)
    # No WP was pre-deducted, so cancellation just marks the prediction cancelled.
    await database.update_prediction_status_db(prediction_id, 'cancelled')
    logger.info(f"[Predictions] #{prediction_id} cancelled — {len(votes)} votes released (no WP was taken)")
    return {'success': True, 'refunded': len(votes), 'title': prediction['title'],
            'message': f'Cancelled — {len(votes)} vote(s) released.'}


async def _dm_winners(bot, prediction, winning_choice, payouts):
    """Best-effort winner DMs (routed through the shared DM queue)."""
    import discord
    for p in payouts:
        try:
            user = bot.get_user(p['user_id']) or await bot.fetch_user(p['user_id'])
            if not user:
                continue
            embed = discord.Embed(
                title="🎉 You Won a Prediction!",
                description=f"**#{prediction['id']}:** {prediction['title']}",
                color=discord.Color.gold(),
            )
            embed.add_field(name="🏆 Outcome", value=winning_choice.upper(), inline=True)
            embed.add_field(name="🌊 Your Stake", value=f"{p['stake']} WP", inline=True)
            embed.add_field(name="🎁 Winnings", value=f"**{p['winnings']} WP**", inline=True)
            embed.add_field(name="📊 Share", value=f"{p['proportion']:.1%} of pool", inline=False)
            await user.send(embed=embed)
        except Exception as exc:
            logger.warning(f"[Predictions] could not DM winner {p['user_id']}: {exc}")


async def setup(bot):
    pass  # utility module — no cog to register
