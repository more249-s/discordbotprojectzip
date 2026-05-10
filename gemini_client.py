import asyncio
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import google.generativeai as genai
from config import Config
import database
from search_tool import SearchTool


class GeminiClient:
    def __init__(self):
        genai.configure(api_key=Config.GEMINI_API_KEY)
        self.system_prompt = (
            "أنت مساعد ذكي فائق السرعة وخبير متعدد المجالات. "
            "تخصصك الأساسي هو خبير في عالم المانهوا والمانجا والويبتون. "
            "لديك معرفة واسعة بالمواقع المختلفة لقراءة وتحميل المانجا، "
            "وتقدر تساعد المستخدمين في إيجاد المانهوا وتتبع الفصول وتنزيلها. "
            "لديك القدرة على البحث في الإنترنت باستخدام أداة البحث المتاحة لك."
        )
        self.search_tool = SearchTool()
        self.tools       = [self.search_tool.search]
        self.model_name  = "gemini-2.0-flash"
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=self.system_prompt,
            tools=self.tools,
        )

    async def get_response(self, user_id: int, prompt: str, image_data=None) -> str:
        if not Config.GEMINI_API_KEY:
            return "❌ مفتاح Gemini API غير موجود."
        try:
            history = await database.get_chat_history(user_id)
            chat    = self.model.start_chat(
                history=history,
                enable_automatic_function_calling=True,
            )
            if image_data:
                response = await asyncio.to_thread(
                    self.model.generate_content, [prompt, image_data]
                )
            else:
                response = await asyncio.to_thread(chat.send_message, prompt)

            text = response.text if hasattr(response, "text") else str(response)
            await database.add_chat_message(user_id, "user",  prompt)
            await database.add_chat_message(user_id, "model", text)
            return text
        except Exception as e:
            return f"حدث خطأ أثناء التواصل مع Gemini: {e}"

    async def analyze_site(self, url: str) -> dict:
        """تحليل موقع مانجا وتحديد نوعه."""
        prompt = (
            f"حلل الموقع: {url}\n"
            "أجب بصيغة JSON فقط بدون أي نص إضافي:\n"
            '{"is_manga_site": true/false, "site_type": "madara|arabic|generic|mangadex|webtoon", '
            '"confidence": 0-100, "reason": "السبب"}\n'
            "site_type يكون:\n"
            "- madara: إذا كان WordPress مع Madara theme (أكثر مواقع المانجا الإنجليزية)\n"
            "- arabic: إذا كان موقع مانجا عربي\n"
            "- mangadex: إذا كان MangaDex أو API مشابه\n"
            "- webtoon: إذا كان موقع ويبتون\n"
            "- generic: إذا كان موقع مانجا لكن بتصميم مختلف\n"
        )
        try:
            response = await asyncio.to_thread(
                self.model.generate_content, prompt
            )
            import re, json
            text = response.text.strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            print(f"[Gemini] analyze_site error: {e}")
        return {"is_manga_site": False, "site_type": "generic", "confidence": 0, "reason": "فشل التحليل"}

    async def clear_history(self, user_id: int):
        await database.clear_chat_history(user_id)
