from .base_provider import BaseProvider
from typing import List, Optional
import asyncio

class GeminiProvider(BaseProvider):
    """
    مزود يعتمد على الذكاء الاصطناعي (Gemini) لتحليل المواقع المعقدة
    التي تفشل معها المزودات العادية.
    """
    def __init__(self, gemini_client, scraper=None):
        super().__init__(scraper)
        self.gemini = gemini_client

    def get_latest_chapter(self, url: str) -> Optional[float]:
        # نستخدم دالة غير متزامنة لأن Gemini يحتاج await
        # ولكن هيكلية Providers حالياً تعتمد على run_in_executor
        # لذلك سنجعل هذه الدالة مجرد واجهة، وننادي Gemini بطريقة متزامنة أو نغير الهيكلية.
        pass

    async def get_latest_chapter_async(self, url: str) -> Optional[float]:
        html = self.fetch_html(url)
        if not html: return None
        
        # تقليل حجم الـ HTML لتقليل التكلفة (أخذ أول 15000 حرف عادة تكفي)
        prompt = f"""
        أنت محلل بيانات. هذا كود HTML لصفحة مانجا/مانهوا:
        {html[:15000]}
        
        مهمتك: استخرج رقم أحدث فصل (Latest Chapter) متوفر في هذا الكود.
        قم بإرجاع "الرقم فقط" (مثال: 124 أو 124.5).
        إذا لم تعثر على أي رقم فصل واضح، قم بإرجاع الكلمة "None".
        لا تكتب أي نص آخر.
        """
        try:
            # We bypass the db history for this specific internal task
            response = await asyncio.to_thread(self.gemini.model.generate_content, prompt)
            text = response.text.strip()
            if text.lower() == "none": return None
            return float(text)
        except Exception as e:
            print(f"GeminiProvider Error: {e}")
            return None

    async def get_all_chapters_async(self, url: str) -> dict:
        html = self.fetch_html(url)
        if not html: return {}
        
        prompt = f"""
        أنت مبرمج ومحلل بيانات. هذا كود HTML لصفحة رئيسية لمانجا/مانهوا:
        {html[:30000]}
        
        مهمتك: استخراج جميع أرقام الفصول وروابطها (URLs) المتوفرة في الكود.
        قم بإرجاع النتيجة بصيغة JSON فقط، بحيث يكون المفتاح هو رقم الفصل (float) والقيمة هي الرابط.
        مثال: {{"1.0": "http://...", "2.0": "http://..."}}
        لا تكتب أي نص أو شرح آخر خارج كود الـ JSON.
        """
        try:
            response = await asyncio.to_thread(self.gemini.model.generate_content, prompt)
            text = response.text.strip()
            if text.startswith("```json"):
                text = text.replace("```json", "").replace("```", "").strip()
            
            import json
            chapters_data = json.loads(text)
            
            # تحويل المفاتيح إلى float
            result = {}
            for k, v in chapters_data.items():
                try:
                    result[float(k)] = v
                except:
                    pass
            return result
        except Exception as e:
            print(f"GeminiProvider get_all_chapters Error: {e}")
            return {}

    async def get_images_async(self, url: str) -> List[str]:
        html = self.fetch_html(url)
        if not html: return []
        
        prompt = f"""
        أنت محلل بيانات. هذا كود HTML لصفحة قراءة فصل مانجا:
        {html[:30000]}
        
        مهمتك: استخرج جميع الروابط (URLs) الخاصة بصور هذا الفصل.
        قم بإرجاع الروابط فقط، بحيث يكون كل رابط في سطر منفصل.
        تأكد من أن الروابط تبدأ بـ http أو https.
        لا تكتب أي نص آخر، روابط فقط.
        """
        try:
            response = await asyncio.to_thread(self.gemini.model.generate_content, prompt)
            lines = response.text.strip().split('\n')
            valid_urls = [line.strip() for line in lines if line.strip().startswith('http')]
            return list(dict.fromkeys(valid_urls))
        except Exception as e:
            print(f"GeminiProvider Image Error: {e}")
            return []
