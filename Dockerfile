FROM python:3.11-slim

# مكتبات النظام اللازمة لـ Pillow وغيرها
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    libjpeg-dev \
    libpng-dev \
    libwebp-dev \
    libopenjp2-7-dev \
    libtiff-dev \
    libzstd-dev \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# تثبيت المتطلبات أولاً (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY . .

# إنشاء مجلدات البيانات
RUN mkdir -p data temp_downloads

# المنفذ الافتراضي (HuggingFace Spaces يستخدم 7860)
ENV PORT=7860
EXPOSE 7860

CMD ["python3", "main.py"]
