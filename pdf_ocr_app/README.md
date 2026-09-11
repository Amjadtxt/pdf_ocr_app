# PDF OCR + Translation Dataset Builder

موقع بيسمحلك ترفع PDF ممسوح ضوئياً (سكان) ويستخرج النص من كل صفحة تلقائياً
(بدون أي تحويل يدوي لصور أو استخدام pdftoppm بنفسك — كل ده بيحصل جوه السيرفر).
كمان بيسمحلك تبني dataset من الكلمات: Word / Meaning / Synonym / Language،
مع تسجيل دخول للمستخدمين.

## المكونات
- **Backend:** Flask (Python)
- **OCR:** pytesseract + pdf2image (Tesseract + Poppler, مثبتين جوه الـ Docker image)
- **الترجمة:** MyMemory API (مجاني، بدون مفتاح)
- **المرادفات:** Datamuse API (مجاني، إنجليزي فقط حالياً)
- **قاعدة البيانات:** SQLite (ملف محلي، تقدر تبدلها بـ PostgreSQN لاحقاً)
- **تسجيل الدخول:** Flask-Login

## تشغيل محلي (اختياري، لو عندك Docker)
```bash
docker build -t pdf-ocr-app .
docker run -p 10000:10000 pdf-ocr-app
```
افتح: http://localhost:10000

## النشر على Render (مجاناً)
1. اعمل حساب على https://render.com وربطه بحساب GitHub بتاعك.
2. ارفع مجلد المشروع ده كـ repository جديد على GitHub.
3. من داشبورد Render: **New > Web Service**.
4. اختار الـ repo، وفي خانة **Environment** اختار **Docker** (مش Python) — عشان
   يستخدم الـ Dockerfile المرفق ويثبت Tesseract و Poppler صح.
5. Render هياخد الـ PORT تلقائي من متغير البيئة، متغيرش حاجة في الـ Dockerfile.
6. من **Environment Variables** ضيف:
   - `SECRET_KEY` = أي قيمة سرية عشوائية
7. اضغط **Create Web Service** واستنى الـ build يخلص (أول مرة بتاخد كذا دقيقة
   عشان بتنزل Tesseract).

ملحوظة: الخطة المجانية على Render بتنوّم السيرفر بعد فترة عدم استخدام،
وأول طلب بعد النوم بياخد شوية وقت يصحى.

## استخدام API الـ OCR مباشرة (من كود تاني)
```
POST /api/ocr?lang=ara+eng
```
تقدر تبعت الملف بطريقتين:
- **multipart/form-data** مع field اسمه `file`
- **JSON**: `{"pdf_base64": "..."}`

الرد:
```json
{"pages": ["نص صفحة 1", "نص صفحة 2"], "page_count": 2}
```

(محتاج تسجيل دخول أولاً — الجلسة بتتحفظ بكوكيز، فلو بتنادي الـ API من كود خارجي
هتحتاج تسجل دخول بنفس الـ session/cookies).

## ملاحظات أمان
- غيّر `SECRET_KEY` في الإنتاج.
- الباسوردات متخزنة مُشفّرة (hash) وليس نص صريح.
- لو حابب تفتح `/api/ocr` كـ API عام بدون تسجيل دخول (لاستخدامه من تطبيقات
  خارجية)، شيل `@login_required` من فوق الدالة في `app.py`، بس ده هيفتح
  الموقع لاستخدام غير محدود من أي حد.
