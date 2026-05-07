import google.generativeai as genai
from config import Config
import database
import asyncio
from search_tool import SearchTool

class GeminiClient:
    def __init__(self):
        genai.configure(api_key=Config.GEMINI_API_KEY)
        self.system_prompt = "أنت مساعد ذكي فائق السرعة وخبير متعدد المجالات. تخصصك الأساسي هو: 1) خبير في عالم المانهوا والمانجا. 2) خبير مالي في باينانس. لديك القدرة على البحث في الإنترنت باستخدام أداة البحث المتاحة لك للحصول على معلومات دقيقة وحالية."
        self.search_tool = SearchTool()
        
        # Define the tools (Functions)
        self.tools = [self.search_tool.search]
        
        self.model_name = 'gemini-2.5-flash'
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=self.system_prompt,
            tools=self.tools
        )
        
        # --- Image Editor Model (Nano Banana) ---
        self.editor_model_name = 'models/nano-banana-pro-preview'
        self.editor_prompt = """أنت خبير محترف ومختص في تبييض المانجا والمانهوا (Manga Cleaner).
مهمتك هي "تنظيف" الصورة المرفقة (Cleaning) بناءً على الوصف المعطى بدقة متناهية.
يجب عليك الالتزام بالقواعد التالية التزاماً أعمى لا يقبل الخطأ:
1. إزالة جميع النصوص الأصلية من داخل فقاعات المحادثة بالكامل لترك الفقاعات فارغة ونظيفة.
2. يُمنع منعاً باتاً إضافة أو كتابة أي نصوص جديدة. مهمتك هي "المسح والتنظيف فقط".
3. الحفاظ تماماً على شكل، لون، ومكان الفقاعة الأصلي دون أي تغيير أو تشويه ولو بمقدار بكسل واحد.
4. التعديل يكون "فقط وحصرياً" على إزالة النص. يُمنع منعاً باتاً تعديل، تغيير، أو المساس بأي جزء من الخلفية، الشخصيات، أو شفافية الصورة (Transparency).
5. يجب أن تبدو النتيجة النهائية أصلية 100% وكأنها صورة خام (Raw) جاهزة للترجمة، مع بقاء كل شيء آخر في الصورة كما هو."""
        
        self.editor_model = genai.GenerativeModel(
            model_name=self.editor_model_name,
            system_instruction=self.editor_prompt
        )
        
    async def get_response(self, user_id, prompt, image_data=None):
        if not Config.GEMINI_API_KEY:
            return "خطأ: لم يتم ضبط مفتاح Gemini API Key في ملف .env"

        try:
            # Get history from DB
            history = await database.get_chat_history(user_id)
            
            # Use enable_automatic_function_calling for seamless search
            chat = self.model.start_chat(history=history, enable_automatic_function_calling=True)
            
            if image_data:
                # Multimodal request
                response = await asyncio.to_thread(self.model.generate_content, [prompt, image_data])
            else:
                # Text-only request with automatic search integration
                response = await asyncio.to_thread(chat.send_message, prompt)
            
            # Save to DB
            await database.add_chat_message(user_id, "user", prompt)
            await database.add_chat_message(user_id, "model", response.text)
            
            return response.text
        except Exception as e:
            return f"حدث خطأ أثناء التواصل مع Gemini: {str(e)}"

    async def clean_image(self, prompt, image_data):
        """
        دالة مخصصة لتنظيف الصور باستخدام موديل nano-banana مع البرومبت الصارم.
        """
        try:
            full_prompt = f"الوصف والتعديل المطلوب: {prompt}"
            response = await asyncio.to_thread(self.editor_model.generate_content, [full_prompt, image_data])
            
            # Since this model edits images, it might return text describing the edit, 
            # or it might return an image blob directly if it's a multimodal-output model.
            return response
        except Exception as e:
            raise Exception(f"خطأ في تعديل الصورة: {str(e)}")
