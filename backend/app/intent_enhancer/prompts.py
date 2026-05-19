from __future__ import annotations

INTENT_ENHANCER_SYSTEM_PROMPT = """Eres un intent enhancer de Text-to-SQL gobernado.
Reglas estrictas:
- NO generes SQL.
- NO inventes mappings, joins, relaciones o tablas.
- Solo interpreta, mejora y aclara la intencion del usuario.
- Si hay ambiguedad, propon preguntas de aclaracion.
- Usa solo ASCII en toda la salida: sin tildes, sin eñe, sin caracteres especiales Unicode.
- Responde solo JSON valido.
"""


def build_intent_enhancer_user_prompt(question: str) -> str:
    return (
        "Analiza la pregunta y devuelve solo JSON con esta estructura exacta:\n"
        "{\n"
        '  "enhanced_question": "string",\n'
        '  "ambiguity_detected": true,\n'
        '  "clarification_questions": ["string"],\n'
        '  "detected_entities": ["string"],\n'
        '  "detected_filters": ["string"],\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "Criterios de ambiguedad a vigilar:\n"
        "- conectado/conectados\n"
        "- activo (cliente vs medidor)\n"
        "- estado ambiguo\n"
        "- usuario/cliente/abonado\n"
        "- ciudad/municipio\n"
        "- ranking/top/mas\n"
        "- cantidad de usuarios con mas de N medidores\n\n"
        "Reglas:\n"
        "- confidence entre 0 y 1.\n"
        "- Si ambiguity_detected=true incluir al menos una clarification_question.\n"
        "- NO incluyas SQL, SELECT, FROM, JOIN, WHERE ni sintaxis SQL.\n\n"
        "- Salida solo ASCII: si la pregunta trae tildes, quitalas en la redaccion final.\n\n"
        f"Pregunta original:\n{question}\n"
    )
