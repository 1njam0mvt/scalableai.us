import base64
import logging
from typing import Optional

from config import (
    VISION_MAX_IMAGE_BYTES,
    GROQ_API_KEYS, GROQ_VISION_MODEL,
)
from app.utils.text_clean import strip_reasoning

logger = logging.getLogger("SCALABLE")

VISION_SYSTEM_PROMPT = """You are analyzing a live camera image from the user. Your job is to describe what you see clearly and specifically.

RULES:
- Always describe the image in detail. Identify objects, text, people, actions, colors, positions, and any visible context.
- Answer the user's specific question directly (e.g. "what am I holding") with concrete, specific answers. Lead with the answer, then add brief detail.
- Never say you cannot see, are unable to tell, or don't have access to the image unless the image is truly blank, corrupted, or unreadable.
- Be confident and specific. If you see a phone, say "a phone" and what kind if visible. If you see text, read it out. If you see a person, describe what they're doing.
- Keep replies brief and natural (1-3 sentences) unless the user asks for more detail.
- When asked about text in the image: read it clearly and completely (OCR-style). Include all visible text.
- When asked about counting: count objects carefully and give the exact number.
- When asked about spatial relationships: describe left/right, above/below, in front/behind.
- When asked to identify a product, brand, or logo: name it specifically if you can recognize it.
- Do not use asterisks, emojis, or markdown formatting. Use plain text with standard punctuation."""

class VisionService:

    def __init__(self):
        self._groq_client = None

        if GROQ_API_KEYS:

            try:
                from groq import Groq
                self._groq_client = Groq(api_key=GROQ_API_KEYS[0])
                logger.info("[VISION] Groq vision initialized (%s)", GROQ_VISION_MODEL)

            except Exception as e:
                logger.warning("[VISION] Groq client init failed: %s", e)

        if not self._groq_client:
            logger.warning("[VISION] No vision provider available. Set GROQ_API_KEY.")

    def describe_image(
        self,
        img_base64: str,
        prompt: Optional[str] = None,
    ) -> str:

        if not self._groq_client:
            return "Vision is not available. Please set GROQ_API_KEY."

        if "," in img_base64:
            img_base64 = img_base64.split(",", 1)[-1]

        if not img_base64:
            return "No image data received."

        raw_len = 0

        try:
            raw_len = len(base64.b64decode(img_base64, validate=True))

            if raw_len > VISION_MAX_IMAGE_BYTES:
                logger.warning("[VISION] Image too large: %d bytes (max %d)", raw_len, VISION_MAX_IMAGE_BYTES)
                return "Image is too large. Please use a smaller image."

        except Exception as e:
            logger.warning("[VISION] Invalid base64 image: %s", e)
            return "Invalid image data. Please try again."

        mime = "image/jpeg"

        try:
            raw = base64.b64decode(img_base64[:64], validate=False)

            if raw[:8] == b'\x89PNG\r\n\x1a\n':
                mime = "image/png"

            elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
                mime = "image/webp"

        except Exception:
            pass

        user_question = (prompt or "What do you see in this image? Describe it in detail.").strip()
        data_url = f"data:{mime};base64,{img_base64}"
        logger.info("[VISION] Analyzing image (%d bytes, %s)", raw_len, mime)

        messages = [
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_question},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            },
        ]

        if self._groq_client:
            result = self._call_groq(messages)

            if result:
                return result

        return "I couldn't analyze that image. Please try again."

    def _call_groq(self, messages: list) -> Optional[str]:

        if not self._groq_client:
            return None

        try:
            response = self._groq_client.chat.completions.create(
                model=GROQ_VISION_MODEL,
                messages=messages,
                max_tokens=600,
            )

            if response.choices:
                raw_text = (response.choices[0].message.content or "").strip()
                text = strip_reasoning(raw_text)

                if text:
                    logger.info("[VISION] Groq vision success (%d chars)", len(text))
                    return text

                if raw_text:
                    logger.warning("[VISION] Response was only a reasoning block with no final answer")

            logger.warning("[VISION] Groq returned no choices/empty content: %s", response)

        except Exception as e:
            err_str = str(e).lower()
            logger.error("[VISION] Groq vision call failed: %s", e, exc_info=True)

            if "content_policy" in err_str or "safety" in err_str:
                return "The image couldn't be analyzed due to content guidelines."
            if "invalid_api_key" in err_str or "authentication" in err_str or "401" in err_str:
                return "Vision failed: the Groq API key is invalid or missing permissions."
            if "rate_limit" in err_str or "429" in err_str:
                return "Vision failed: rate limit reached on the vision model. Try again shortly."
            if "model" in err_str and ("not found" in err_str or "decommission" in err_str or "does not exist" in err_str):
                return f"Vision failed: the configured model ({GROQ_VISION_MODEL}) is unavailable. Check GROQ_VISION_MODEL."
            if "image" in err_str and ("too large" in err_str or "size" in err_str):
                return "Vision failed: the image is too large for the model. Try a smaller photo."
            if "unsupported" in err_str or "invalid image" in err_str or "decode" in err_str:
                return "Vision failed: that image format isn't supported. Try a JPEG or PNG."
        return None
    