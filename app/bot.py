# bot.py
import os
import io
import asyncio
from datetime import time as dtime, timezone
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
import json
from pathlib import Path

import db as dbmod
import scraper
from formatters import render_skill_line, render_skill_with_upgrade, render_skill_desc_only, render_skill_header, _fmt_skill_table, _fmt_cost
from pathlib import Path
import json
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_PATH = BASE_DIR / "data" / "students.min.en.json"
with open(DATA_PATH, encoding="utf-8") as f:
    raw = json.load(f)

# Your file is a dict: {"10000": {...}, "10001": {...}, ...}
if isinstance(raw, dict):
    STUDENTS = list(raw.values())
elif isinstance(raw, list):
    STUDENTS = raw
else:
    raise RuntimeError(f"Unexpected students JSON root type: {type(raw)}")

# Lookups (fast)
STUDENTS_BY_PATH = {
    s.get("PathName", "").lower(): s
    for s in STUDENTS
    if isinstance(s, dict) and s.get("PathName")
}
STUDENTS_BY_NAME = {
    s.get("Name", "").lower(): s
    for s in STUDENTS
    if isinstance(s, dict) and s.get("Name")
}

# Autocomplete pool: (display label, value key)
# We set value = PathName (lowercase) so commands can lookup reliably.
STUDENT_AC_POOL: list[tuple[str, str]] = []
for s in STUDENTS:
    if not isinstance(s, dict):
        continue
    name = (s.get("Name") or "").strip()
    pathname = (s.get("PathName") or "").strip().lower()
    if not name or not pathname:
        continue
    STUDENT_AC_POOL.append((name, pathname))

# stable order; actual search ranking happens in the autocomplete callback
STUDENT_AC_POOL.sort(key=lambda x: x[0].lower())

print(f"[students] Loaded {len(STUDENTS_BY_PATH)} students. Autocomplete entries: {len(STUDENT_AC_POOL)}")

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
X_BEARER = os.environ["X_BEARER_TOKEN"]
X_USER_ID = os.environ["X_USER_ID"]
X_USERNAME = os.getenv("X_USERNAME", "Blue_ArchiveJP")
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "10"))
JP_PREFIX = os.getenv("JP_PREFIX", "【生徒紹介】")
DEV_DISCORD_USER_ID = int(os.environ["DEV_DISCORD_USER_ID"])
DM_DAILY_STATUS = os.getenv("DM_DAILY_STATUS", "true").lower() == "true"
DB_PATH = os.getenv("DB_PATH", "./state.db")
POST_HOUR_UTC = int(os.getenv("POST_HOUR_UTC", "3"))
POST_MINUTE_UTC = int(os.getenv("POST_MINUTE_UTC", "10"))
X_USER_ID2 = os.environ["X_USER_ID2"]
X_USERNAME2 = os.getenv("X_USERNAME2", "EN_BlueArchive")
EN_PREFIXES = [
    "[Unique Pick-Up Recruitment Preview]",
    "[Pick-Up Recruitment Preview]",
    "[Unique Rerun Pick-Up Recruitment Preview]",
    "[Rerun Pick-Up Recruitment Preview]",
]
EN_POST_HOUR_UTC = int(os.getenv("EN_POST_HOUR_UTC", "7"))
EN_POST_MINUTE_UTC = int(os.getenv("EN_POST_MINUTE_UTC", "20"))
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

conn = dbmod.connect(DB_PATH)

SQUAD_TYPE_MAP = {
    "Main": "Striker",
    "Support": "Special",
}

def is_admin(interaction: discord.Interaction) -> bool:
    perms = interaction.user.guild_permissions
    return perms.manage_guild or perms.administrator

def _rank(query: str, label: str) -> tuple[int, int]:
    q = query.lower()
    l = label.lower()
    # best matches first: startswith > contains; shorter names first
    if l.startswith(q):
        return (0, len(l))
    if q in l:
        return (1, len(l))
    return (2, len(l))

async def student_autocomplete(interaction: discord.Interaction, current: str):
    q = (current or "").strip().lower()

    if not q:
        picks = STUDENT_AC_POOL[:25]
    else:
        matches = [(label, key) for (label, key) in STUDENT_AC_POOL if q in label.lower()]
        matches.sort(key=lambda x: _rank(q, x[0]))
        picks = matches[:25]

    return [app_commands.Choice(name=label, value=key) for (label, key) in picks]

def _trunc(s: str, n: int = 950) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"

def _skill_text(skill: dict) -> str:
    # Skill name + desc, no "Yuuka's X Skill:" header (compact for embed fields)
    name = skill.get("Name", "Unknown")
    desc = render_skill_desc_only(skill)  # from your formatters.py
    cost = skill.get("Cost")
    cost_txt = f" (Cost: {cost[0]})" if isinstance(cost, list) and cost else ""
    return f"**{name}{cost_txt}**\n{desc}"

@tree.command(name="setup", description="Choose which channel Azure A.R.O.N.A posts into (admin only).")
@app_commands.describe(channel="Channel to post Blue Archive updates")
async def setup_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.guild:
        return await interaction.response.send_message("Run this inside a server.", ephemeral=True)
    if not is_admin(interaction):
        return await interaction.response.send_message("You need **Manage Server** to run this.", ephemeral=True)

    dbmod.upsert_guild_config(conn, interaction.guild_id, channel.id, enabled=1)
    await interaction.response.send_message(f"✅ Posting enabled in {channel.mention}", ephemeral=True)

@tree.command(name="disable", description="Disable posting in this server (admin only).")
async def disable_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this inside a server.", ephemeral=True)
    if not is_admin(interaction):
        return await interaction.response.send_message("You need **Manage Server** to run this.", ephemeral=True)

    dbmod.set_enabled(conn, interaction.guild_id, 0)
    await interaction.response.send_message("🛑 Posting disabled for this server.", ephemeral=True)

@tree.command(name="enable", description="Enable posting in this server (admin only).")
async def enable_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this inside a server.", ephemeral=True)
    if not is_admin(interaction):
        return await interaction.response.send_message("You need **Manage Server** to run this.", ephemeral=True)

    cfg = dbmod.get_guild_config(conn, interaction.guild_id)
    if not cfg:
        return await interaction.response.send_message("Run `/setup` first to pick a channel.", ephemeral=True)

    channel_id, _enabled = cfg
    dbmod.upsert_guild_config(conn, interaction.guild_id, channel_id, enabled=1)
    await interaction.response.send_message("✅ Posting enabled for this server.", ephemeral=True)

@tree.command(name="status", description="Show bot config status for this server.")
async def status_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this inside a server.", ephemeral=True)

    cfg = dbmod.get_guild_config(conn, interaction.guild_id)
    if not cfg:
        return await interaction.response.send_message("Not configured. Admin should run `/setup`.", ephemeral=True)

    channel_id, enabled = cfg
    ch = interaction.guild.get_channel(channel_id)
    ch_text = ch.mention if ch else f"(missing channel id: {channel_id})"
    await interaction.response.send_message(f"Channel: {ch_text}\nEnabled: {bool(enabled)}", ephemeral=True)

@tree.command(name="testlatest", description="Force post the latest student intro (dev only).")
async def testlatest_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this inside a server.", ephemeral=True)

    if interaction.user.id != DEV_DISCORD_USER_ID:
        return await interaction.response.send_message("🚫 This command is developer-only.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)  # 👈 defer before any slow work

    tweets = await asyncio.to_thread(
        scraper.fetch_recent_student_intros,
        X_BEARER, X_USER_ID, FETCH_LIMIT, JP_PREFIX,
    )

    if not tweets:
        return await interaction.followup.send("No student intros found.", ephemeral=True)  # 👈 followup

    t = tweets[0]
    post_url = f"https://x.com/{X_USERNAME}/status/{t['id']}"
    msg = f"🧪 **Test: Sensei! New Student just dropped!**\n<{post_url}>"

    files = await asyncio.to_thread(scraper.download_images, t["media_urls"]) if t["media_urls"] else []

    cfg = dbmod.get_guild_config(conn, interaction.guild_id)
    if not cfg:
        return await interaction.followup.send("No channel configured. Run /setup first.", ephemeral=True)

    channel_id, enabled = cfg
    if not enabled:
        return await interaction.followup.send("Posting is disabled for this server. Run /enable first.", ephemeral=True)

    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    discord_files = [discord.File(fp=io.BytesIO(blob), filename=fname) for fname, blob in files]
    await channel.send(content=msg, files=discord_files if discord_files else None)

    await interaction.followup.send("✅ Posted test message.", ephemeral=True)  # 👈 followup

@tree.command(name="ex", description="Show a student's EX skill with stats per rank.")
@app_commands.describe(student="Student name, e.g., Yuuka")
@app_commands.autocomplete(student=student_autocomplete)
async def ex_cmd(interaction: discord.Interaction, student: str):
    await interaction.response.defer(thinking=True)

    try:
        key = (student or "").strip().lower()
        s = STUDENTS_BY_PATH.get(key) or STUDENTS_BY_NAME.get(key)
        if not s:
            return await interaction.followup.send("Student not found.", ephemeral=True)

        skills = s.get("Skills") or {}
        ex = skills.get("Ex")
        if not ex:
            return await interaction.followup.send(
                f"No EX skill found for {s.get('Name', 'that student')}.",
                ephemeral=True
            )

        name = s.get("Name", "Unknown")
        skill_name = ex.get("Name", "Unknown")
        body = _fmt_skill_table(ex, ranks=5)
        cost_txt = _fmt_cost(ex, ranks=5)
        msg = f"**{name}'s EX Skill — {skill_name}{cost_txt}**\n{body}"
        await interaction.followup.send(_trunc(msg, 2000))

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{type(e).__name__}: {e}`", ephemeral=True)
        raise


@tree.command(name="ns", description="Show a student's Normal Skill with stats per rank.")
@app_commands.describe(student="Student name, e.g., Yuuka")
@app_commands.autocomplete(student=student_autocomplete)
async def ns_cmd(interaction: discord.Interaction, student: str):
    await interaction.response.defer(thinking=True)

    try:
        key = (student or "").strip().lower()
        s = STUDENTS_BY_PATH.get(key) or STUDENTS_BY_NAME.get(key)
        if not s:
            return await interaction.followup.send("Student not found.", ephemeral=True)

        skills = s.get("Skills") or {}
        base = skills.get("Public")
        if not base:
            return await interaction.followup.send(
                f"No Normal Skill found for {s.get('Name', 'that student')}.",
                ephemeral=True
            )

        name = s.get("Name", "Unknown")
        skill_name = base.get("Name", "Unknown")
        body = _fmt_skill_table(base, ranks=10)

        upgrade = skills.get("GearPublic")
        upgrade_txt = ""
        if upgrade:
            upgrade_body = _fmt_skill_table(upgrade, ranks=10)
            upgrade_txt = f"\n\n**Upgrade (Unique Item T2) — {upgrade.get('Name', 'Upgrade')}**\n{upgrade_body}"

        msg = f"**{name}'s Normal Skill — {skill_name}**\n{body}{upgrade_txt}"
        await interaction.followup.send(_trunc(msg, 2000))

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{type(e).__name__}: {e}`", ephemeral=True)
        raise


@tree.command(name="enhanced", description="Show a student's Enhanced Skill with stats per rank.")
@app_commands.describe(student="Student name, e.g., Yuuka")
@app_commands.autocomplete(student=student_autocomplete)
async def enhanced_cmd(interaction: discord.Interaction, student: str):
    await interaction.response.defer(thinking=True)

    try:
        key = (student or "").strip().lower()
        s = STUDENTS_BY_PATH.get(key) or STUDENTS_BY_NAME.get(key)
        if not s:
            return await interaction.followup.send("Student not found.", ephemeral=True)

        skills = s.get("Skills") or {}
        base = skills.get("Passive")
        if not base:
            return await interaction.followup.send(
                f"No Enhanced Skill found for {s.get('Name', 'that student')}.",
                ephemeral=True
            )

        name = s.get("Name", "Unknown")
        skill_name = base.get("Name", "Unknown")
        body = _fmt_skill_table(base, ranks=10)

        upgrade = skills.get("WeaponPassive")
        upgrade_txt = ""
        if upgrade:
            upgrade_body = _fmt_skill_table(upgrade, ranks=10)
            upgrade_txt = f"\n\n**Upgrade (UE40) — {upgrade.get('Name', 'Upgrade')}**\n{upgrade_body}"

        msg = f"**{name}'s Enhanced Skill — {skill_name}**\n{body}{upgrade_txt}"
        await interaction.followup.send(_trunc(msg, 2000))

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{type(e).__name__}: {e}`", ephemeral=True)
        raise


@tree.command(name="sub", description="Show a student's Sub Skill with stats per rank.")
@app_commands.describe(student="Student name, e.g., Yuuka")
@app_commands.autocomplete(student=student_autocomplete)
async def sub_cmd(interaction: discord.Interaction, student: str):
    await interaction.response.defer(thinking=True)

    try:
        key = (student or "").strip().lower()
        s = STUDENTS_BY_PATH.get(key) or STUDENTS_BY_NAME.get(key)
        if not s:
            return await interaction.followup.send("Student not found.", ephemeral=True)

        skills = s.get("Skills") or {}
        sk = skills.get("Sub") or skills.get("ExtraPassive")
        if not sk:
            return await interaction.followup.send(
                f"No Sub Skill found for {s.get('Name', 'that student')}.",
                ephemeral=True
            )

        name = s.get("Name", "Unknown")
        skill_name = sk.get("Name", "Unknown")
        body = _fmt_skill_table(sk, ranks=10)
        msg = f"**{name}'s Sub Skill — {skill_name}**\n{body}"
        await interaction.followup.send(_trunc(msg, 2000))

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{type(e).__name__}: {e}`", ephemeral=True)
        raise

@tree.command(name="student", description="Show a student's full kit.")
@app_commands.describe(student="Student name, e.g., Yuuka")
@app_commands.autocomplete(student=student_autocomplete)
async def student_cmd(interaction: discord.Interaction, student: str):
    await interaction.response.defer(thinking=True)

    try:
        key = (student or "").strip().lower()
        s = STUDENTS_BY_PATH.get(key) or STUDENTS_BY_NAME.get(key)
        if not s:
            return await interaction.followup.send("Student not found.", ephemeral=True)

        name = s.get("Name", "Unknown")
        skills = s.get("Skills") or {}
        
        raw_squad = s.get("SquadType", "")
        squad = SQUAD_TYPE_MAP.get(raw_squad, raw_squad)
        position = s.get("Position", "")
        role = s.get("TacticRole", "")
        armor = s.get("ArmorType", "")
        bullet = s.get("BulletType", "")

        header_bits = [x for x in [squad, position, role, armor, bullet] if x]
        header = " • ".join(header_bits)

        embed = discord.Embed(
            title=name,
            description=header,
            color=discord.Color.blue()
        )

        # EX
        ex = skills.get("Ex")
        if ex:
            text = f"{render_skill_header('EX', ex)}\n{render_skill_desc_only(ex)}"
            embed.add_field(name="EX", value=text, inline=False)

        # NS
        ns = skills.get("Public")
        if ns:
            text = f"{render_skill_header('NS', ns)}\n{render_skill_desc_only(ns)}"

            ns_up = skills.get("GearPublic")
            if ns_up:
                text += f"\n\nUpgrade (Unique Item T2) - {ns_up.get('Name','Upgrade')}\n"
                text += render_skill_desc_only(ns_up)

            embed.add_field(name="NS", value=text, inline=False)

        # Enhanced
        enh = skills.get("Passive")
        if enh:
            text = f"{render_skill_header('Enhanced', enh)}\n{render_skill_desc_only(enh)}"

            enh_up = skills.get("WeaponPassive")
            if enh_up:
                text += f"\n\nUpgrade (UE40) - {enh_up.get('Name','Upgrade')}\n"
                text += render_skill_desc_only(enh_up)

            embed.add_field(name="Enhanced", value=text, inline=False)

        # Sub
        sub = skills.get("Sub") or skills.get("ExtraPassive")
        if sub:
            text = f"{render_skill_header('Sub', sub)}\n{render_skill_desc_only(sub)}"
            embed.add_field(name="Sub", value=text, inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{type(e).__name__}: {e}`", ephemeral=True)
        raise

async def post_to_all_servers(tweet_id: str, message: str, files: list[tuple[str, bytes]]):
    targets = dbmod.list_enabled_channels(conn)

    for guild_id, channel_id in targets:
        channel = client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(channel_id)
            except discord.NotFound:
                # Channel no longer exists
                dbmod.set_enabled(conn, guild_id, 0)
                await dm_dev(f"⚠️ Disabled guild `{guild_id}` — channel `{channel_id}` not found.")
                continue
            except Exception as e:
                await dm_dev(f"⚠️ Could not fetch channel `{channel_id}` in guild `{guild_id}`: {e}")
                continue

        try:
            discord_files = [
                discord.File(fp=io.BytesIO(blob), filename=fname)
                for fname, blob in files
            ]
            await channel.send(content=message, files=discord_files if discord_files else None)
            await asyncio.sleep(1)
        except discord.Forbidden:
            # Bot lost permissions
            dbmod.set_enabled(conn, guild_id, 0)
            await dm_dev(f"⚠️ Disabled guild `{guild_id}` — missing permissions in channel `{channel_id}`.")
        except discord.NotFound:
            # Channel deleted between fetch and send
            dbmod.set_enabled(conn, guild_id, 0)
            await dm_dev(f"⚠️ Disabled guild `{guild_id}` — channel `{channel_id}` was deleted.")
        except Exception as e:
            # Unexpected error — don't disable, just notify
            await dm_dev(f"⚠️ Failed to post in guild `{guild_id}`, channel `{channel_id}`: {type(e).__name__}: {e}")

async def dm_dev(message: str):
    if not DM_DAILY_STATUS:
        return
    try:
        user = await client.fetch_user(DEV_DISCORD_USER_ID)
        await user.send(message)
    except Exception as e:
        # If DMs are closed / fetch fails, don't crash the bot
        print("DM to dev failed:", repr(e))

@tasks.loop(time=dtime(hour=POST_HOUR_UTC, minute=POST_MINUTE_UTC, tzinfo=timezone.utc))
async def daily_check():
    try:
        tweets = await asyncio.to_thread(
            scraper.fetch_recent_student_intros,
            X_BEARER, X_USER_ID, FETCH_LIMIT, JP_PREFIX,
        )

        posted = 0
        skipped_seen = 0

        for t in tweets:
            if dbmod.seen(conn, t["id"]):
                skipped_seen += 1
                continue

            post_url = f"https://x.com/{X_USERNAME}/status/{t['id']}"
            msg = f"🎉 **Sensei! New Student just dropped!**\n<{post_url}>"

            files = await asyncio.to_thread(scraper.download_images, t["media_urls"]) if t["media_urls"] else []
            await post_to_all_servers(t["id"], msg, files)
            dbmod.mark_seen(conn, t["id"])
            posted += 1

        # DM summary once per run
        await dm_dev(
            f"✅ Daily check complete.\n"
            f"- Found intros (after filter): {len(tweets)}\n"
            f"- Posted new: {posted}\n"
            f"- Skipped (already seen): {skipped_seen}"
        )

    except Exception as e:
        # DM the error (keep it short but useful)
        await dm_dev(f"❌ Daily check FAILED: `{type(e).__name__}: {e}`")
        raise  # still log the traceback in your console

@tasks.loop(time=dtime(hour=EN_POST_HOUR_UTC, minute=EN_POST_MINUTE_UTC, tzinfo=timezone.utc))
async def gacha_notice_check():
    # Only run on Fridays (weekday 4)
    from datetime import datetime, timezone as tz
    if datetime.now(tz.utc).weekday() != 4:
        return

    try:
        tweets = await asyncio.to_thread(
            scraper.fetch_gacha_notices,
            X_BEARER, X_USER_ID2, 20, EN_PREFIXES,
        )

        posted = 0
        for t in tweets:
            if dbmod.seen(conn, t["id"]):
                continue

            post_url = f"https://x.com/{X_USERNAME2}/status/{t['id']}"
            msg = f"📢 **Sensei! Upcoming Gacha Notice!**\n<{post_url}>"

            # Save to gacha_notices table
            dbmod.save_gacha_notice(
                conn,
                post_id=t["id"],
                created_at=t["created_at"],
                text=t["text"],
                media_urls=t["media_urls"],
                post_url=post_url,
            )
            dbmod.mark_seen(conn, t["id"])

            files = await asyncio.to_thread(scraper.download_images, t["media_urls"]) if t["media_urls"] else []
            await post_to_all_servers(t["id"], msg, files)
            posted += 1

        await dm_dev(
            f"📢 Gacha notice check complete.\n"
            f"- Found: {len(tweets)}\n"
            f"- Posted new: {posted}"
        )

    except Exception as e:
        await dm_dev(f"❌ Gacha notice check FAILED: `{type(e).__name__}: {e}`")
        raise

@tree.command(name="gachapreview", description="Show the latest gacha notices from Blue Archive EN.")
async def gachapreview_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this inside a server.", ephemeral=True)

    await interaction.response.defer(thinking=True)

    try:
        notices = dbmod.get_recent_gacha_notices(conn, limit=5)

        if not notices:
            return await interaction.followup.send("No gacha notices stored yet. Check back after Friday 7 AM UTC.")

        for n in notices:
            # Download first image if available
            image_file = None
            if n["media_urls"]:
                files = await asyncio.to_thread(scraper.download_images, [n["media_urls"][0]])
                if files:
                    fname, blob = files[0]
                    image_file = discord.File(fp=io.BytesIO(blob), filename=fname)

            embed = discord.Embed(
                title=n["text"].split("\n")[0].strip(),
                url=n["post_url"],
                color=discord.Color.gold()
            )

            # Body text (skip the first line since it's the title)
            body_lines = n["text"].split("\n")[1:]
            body = "\n".join(body_lines).strip()
            if body:
                embed.description = _trunc(body, 1024)

            if image_file:
                embed.set_image(url=f"attachment://{image_file.filename}")

            await interaction.followup.send(
                embed=embed,
                file=image_file if image_file else discord.utils.MISSING
            )

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{type(e).__name__}: {e}`", ephemeral=True)
        raise

@tree.command(name="currentbanner", description="Show banners posted in the last 7 days.")
async def currentbanner_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this inside a server.", ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        from datetime import datetime, timezone as tz, timedelta
        import re

        notices = dbmod.get_recent_gacha_notices(conn, limit=10)

        if not notices:
            return await interaction.followup.send(
                "No banner data yet. Check back after the weekly update.",
                ephemeral=True
            )

        cutoff = datetime.now(tz.utc) - timedelta(days=7)
        recent = [
            n for n in notices
            if datetime.fromisoformat(n['created_at'].replace('Z', '+00:00')) >= cutoff
        ]

        if not recent:
            return await interaction.followup.send(
                "No banners posted in the last 7 days.",
                ephemeral=True
            )

        def extract_students(text: str) -> list[str]:
            names = []
            for line in text.split('\n'):
                line = line.strip()
                if 'Pick-Up Student:' in line:
                    part = line.split('Pick-Up Student:', 1)[-1].strip()
                    part = re.sub(r'^\d+[★*]\s*', '', part)
                    names.append(part)
            return names

        # Build summary text
        summary_lines = ["📢 **Current Banners (Last 7 Days)**\n"]
        for n in recent:
            students = extract_students(n['text'])
            label = n['text'].split('\n')[0].strip()
            student_text = ', '.join(students) if students else 'Unknown'
            summary_lines.append(f"**{label}**\n{student_text}\n[View Post](<{n['post_url']}>)")

        summary = "\n\n".join(summary_lines)

        # Download first image from each notice
        image_files = []
        for n in recent[:4]:
            if n['media_urls']:
                files = await asyncio.to_thread(scraper.download_images, [n['media_urls'][0]])
                if files:
                    fname, blob = files[0]
                    unique_fname = f"banner_{n['post_id']}_{fname}"
                    image_files.append(discord.File(fp=io.BytesIO(blob), filename=unique_fname))

        await interaction.followup.send(
            content=summary,
            files=image_files if image_files else discord.utils.MISSING,
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{type(e).__name__}: {e}`", ephemeral=True)
        raise

@tree.command(name="testgachapreview", description="Dev only: pull fresh gacha notices from X and post to this server.")
async def testgachapreview_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this inside a server.", ephemeral=True)

    if interaction.user.id != DEV_DISCORD_USER_ID:
        return await interaction.response.send_message("🚫 This command is developer-only.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    try:
        tweets = await asyncio.to_thread(scraper.fetch_gacha_notices, 
            X_BEARER, X_USER_ID2, 20, EN_PREFIXES)

        if not tweets:
            return await interaction.followup.send("No gacha notices found on X.", ephemeral=True)

        cfg = dbmod.get_guild_config(conn, interaction.guild_id)
        if not cfg:
            return await interaction.followup.send("No channel configured. Run /setup first.", ephemeral=True)

        channel_id, enabled = cfg
        if not enabled:
            return await interaction.followup.send("Posting is disabled for this server. Run /enable first.", ephemeral=True)

        channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)

        new_count = 0
        for t in tweets:
            post_url = f"https://x.com/{X_USERNAME2}/status/{t['id']}"

            # Save to DB regardless of seen status (test scenario)
            dbmod.save_gacha_notice(
                conn,
                post_id=t["id"],
                created_at=t["created_at"],
                text=t["text"],
                media_urls=t["media_urls"],
                post_url=post_url,
            )
            dbmod.mark_seen(conn, t["id"])

            msg = f"🧪 **Test Gacha Notice**\n<{post_url}>"
            files = await asyncio.to_thread(scraper.download_images, t["media_urls"]) if t["media_urls"] else []
            discord_files = [discord.File(fp=io.BytesIO(blob), filename=fname) for fname, blob in files]
            await channel.send(content=msg, files=discord_files if discord_files else None)
            new_count += 1

        await interaction.followup.send(f"✅ Pulled and posted {new_count} gacha notice(s).", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{type(e).__name__}: {e}`", ephemeral=True)
        raise

@tasks.loop(time=dtime(hour=3, minute=0, tzinfo=timezone.utc))
async def update_student_data():
    from datetime import datetime, timezone as tz
    if datetime.now(tz.utc).weekday() != 0:  # 0 = Monday
        return

    try:
        import urllib.request
        url = "https://schaledb.com/data/en/students.min.json"
        dest = DATA_PATH

        await asyncio.to_thread(urllib.request.urlretrieve, url, dest)

        # Reload the data into memory
        global STUDENTS, STUDENTS_BY_PATH, STUDENTS_BY_NAME, STUDENT_AC_POOL

        with open(dest, encoding="utf-8") as f:
            raw = json.load(f)

        if isinstance(raw, dict):
            STUDENTS = list(raw.values())
        elif isinstance(raw, list):
            STUDENTS = raw

        STUDENTS_BY_PATH = {
            s.get("PathName", "").lower(): s
            for s in STUDENTS
            if isinstance(s, dict) and s.get("PathName")
        }
        STUDENTS_BY_NAME = {
            s.get("Name", "").lower(): s
            for s in STUDENTS
            if isinstance(s, dict) and s.get("Name")
        }
        STUDENT_AC_POOL = []
        for s in STUDENTS:
            if not isinstance(s, dict):
                continue
            name = (s.get("Name") or "").strip()
            pathname = (s.get("PathName") or "").strip().lower()
            if not name or not pathname:
                continue
            STUDENT_AC_POOL.append((name, pathname))
        STUDENT_AC_POOL.sort(key=lambda x: x[0].lower())

        print(f"[students] Reloaded {len(STUDENTS_BY_PATH)} students.", flush=True)
        await dm_dev(f"✅ Student data updated from SchaleDB. {len(STUDENTS_BY_PATH)} students loaded.")

    except Exception as e:
        await dm_dev(f"❌ Student data update FAILED: `{type(e).__name__}: {e}`")
        raise

@client.event
async def on_ready():
    print("🔥 on_ready triggered", flush=True)
    print(f"Logged in as {client.user} (id={client.user.id})", flush=True)

    try:
        DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0"))
        if DEV_GUILD_ID:
            guild = discord.Object(id=DEV_GUILD_ID)
            #tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            print(f"⚡ Commands synced instantly to dev guild {DEV_GUILD_ID}", flush=True)

        await tree.sync()
        print("Slash commands synced globally.", flush=True)
    except Exception as e:
        print(f"❌ Sync failed: {e}", flush=True)

    if not daily_check.is_running():
        daily_check.start()
        print("🕒 daily_check started", flush=True)

    if not gacha_notice_check.is_running():
        gacha_notice_check.start()
        print("📢 gacha_notice_check started", flush=True)

    if not update_student_data.is_running():
        update_student_data.start()
        print("📚 update_student_data started", flush=True)

client.run(DISCORD_TOKEN)

#restart 