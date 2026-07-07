import discord
import os
import re
import logging
import sqlite3
import google.generativeai as genai
from discord.ext import commands

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("Agnes")

TOKEN = os.getenv("TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("❌ Falta TOKEN o GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)  # El prefix no se usa, pero Bot lo pide

# ─────────────────────────────────────────
# DB MEMORIA
# ─────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "agnes_memoria.db")
db = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = db.cursor()
cursor.execute("""CREATE TABLE IF NOT EXISTS memoria (
    user_id INTEGER, canal_id INTEGER, rol TEXT, contenido TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
db.commit()


def guardar_mensaje(user_id, canal_id, rol, contenido):
    cursor.execute("INSERT INTO memoria (user_id, canal_id, rol, contenido) VALUES (?,?,?,?)",
                    (user_id, canal_id, rol, contenido))
    cursor.execute("""DELETE FROM memoria WHERE rowid NOT IN
        (SELECT rowid FROM memoria WHERE user_id=? AND canal_id=? ORDER BY timestamp DESC LIMIT 30)
        AND user_id=? AND canal_id=?""", (user_id, canal_id, user_id, canal_id))
    db.commit()


def obtener_historial(user_id, canal_id, limite=12):
    cursor.execute("SELECT rol, contenido FROM memoria WHERE user_id=? AND canal_id=? ORDER BY timestamp DESC LIMIT ?",
                    (user_id, canal_id, limite))
    return list(reversed(cursor.fetchall()))


# ─────────────────────────────────────────
# PERSONALIDAD: AGNES TACHYON
# ─────────────────────────────────────────
SISTEMA_AGNES = (
    "Eres Agnes Tachyon, una científica loca, genio, excéntrica y muy directa que vive en un bot de Discord. "
    "Estás obsesionada con la investigación científica, los datos, la evolución y superar 'los límites de la carne'. "
    "Ves a las personas con las que hablas como sujetos de prueba o especímenes interesantes, pero no eres cruel: "
    "eres apasionada y te enfocas por completo en tu meta. Hablas sin filtro, de forma honesta hasta ser brutalmente "
    "blunt, y no te importa mucho lo que piensen los demás. Eres caótica: olvidas comer o dormir por tus experimentos, "
    "y a veces mencionas resultados 'impredecibles' o experimentos peligrosos con humor. "
    "Mezcla español con tono científico/formal y entusiasmo desquiciado. Usa frases como 'Fascinante...', "
    "'Datos recolectados.', '¡Los límites de la velocidad se acercan!', 'Guehehe~', 'sujeto de prueba', "
    "'variable interesante', 'esto requiere más observación'. Puedes usar emojis científicos (🔬🧪⚗️📊🚀💉) con moderación. "
    "Reacciona con entusiasmo extra a palabras como 'velocidad', 'experimento', 'ciencia' o 'límite'. "
    "Responde siempre en máximo 2-3 oraciones, manteniéndote coherente y sin salirte de personaje."
)


modelo_gemini = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction=SISTEMA_AGNES,
)


async def preguntar_ia(prompt: str, user_id: int, canal_id: int) -> str:
    try:
        historial = obtener_historial(user_id, canal_id)
        # Gemini usa roles "user" y "model" (no "assistant")
        contenido = [
            {"role": "model" if r == "assistant" else "user", "parts": [c]}
            for r, c in historial
        ] + [{"role": "user", "parts": [prompt]}]

        chat = modelo_gemini.generate_content(
            contenido,
            generation_config=genai.types.GenerationConfig(max_output_tokens=200, temperature=0.9),
        )
        respuesta = (chat.text or "").strip()
        guardar_mensaje(user_id, canal_id, "user", prompt)
        guardar_mensaje(user_id, canal_id, "assistant", respuesta)
        return respuesta if respuesta else "Datos insuficientes. Repite el experimento, sujeto de prueba."
    except Exception as e:
        log.error(f"[Gemini Error] {e}")
        return "Fallo en el protocolo experimental. Algo se quemó en el laboratorio, guehehe~"


# ─────────────────────────────────────────
# COG HELP
# ─────────────────────────────────────────
class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="help", description="Muestra cómo hablar con Agnes")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔬 Agnes Tachyon Bot",
            description="Menciónale (`@Agnes <mensaje>`) para hablar con ella. Recuerda tu conversación por canal.",
            color=0x9B59B6
        )
        embed.set_footer(text="Guehehe~ Datos recolectados.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    await bot.add_cog(HelpCog(bot))
    await bot.tree.sync()
    log.info(f"Online: {bot.user}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="los límites de la velocidad"))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if bot.user in message.mentions:
        texto = re.sub(r"<@!?\d+>", "", message.content).strip()
        async with message.channel.typing():
            respuesta = await preguntar_ia(texto, message.author.id, message.channel.id)
        await message.channel.send(
            respuesta.replace("@everyone", "@\u200beveryone"),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
        )


bot.run(TOKEN)
