"""OCR: đọc chữ trong ảnh bằng EasyOCR, hỗ trợ tiếng Việt và tiếng Anh."""
import re

import cv2
import easyocr

URL_RE = re.compile(r"(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}(?:/[^\s]*)?", re.I)
PHONE_RE = re.compile(r"(?:\+?84|0)(?:[\s.]?\d){8,10}")


class OCREngine:
    def __init__(self, langs=("vi", "en"), gpu=False, min_conf=0.4):
        # Tạo bộ đọc một lần; lần đầu EasyOCR có thể cần tải model.
        self.reader = easyocr.Reader(list(langs), gpu=gpu)
        self.min_conf = min_conf

    @staticmethod
    def _preprocess(img):
        """Hàm chỉ dùng ảnh truyền vào, không dùng thuộc tính self nên là staticmethod."""
        height = img.shape[0]
        width = img.shape[1]

        if max(height, width) < 1200:
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        return img

    def read(self, path: str) -> dict:
        """Đọc một ảnh và trả về nội dung, URL và số điện thoại xuất hiện trong ảnh."""
        image = cv2.imread(path)
        if image is None:
            return {"text": "", "urls": [], "phones": []}

        image = self._preprocess(image)
        detections = self.reader.readtext(image, detail=1, paragraph=False)
        text_lines = []

        # Mỗi detection gồm: vị trí chữ, nội dung chữ, độ tin cậy.
        for detection in detections:
            detected_text = detection[1]
            confidence = detection[2]
            if confidence >= self.min_conf:
                text_lines.append(detected_text)

        text = "\n".join(text_lines)
        urls = set(URL_RE.findall(text))
        phones = set()

        for phone in PHONE_RE.findall(text):
            phones.add(phone.strip())

        return {
            "text": text,
            "urls": sorted(urls),
            "phones": sorted(phones),
        }
