def _has_decoder_fill(image):
    import cv2

    height, width = image.shape[:2]
    neutral = cv2.inRange(image, (128, 128, 128), (128, 128, 128))
    count = cv2.countNonZero(neutral)
    pixels = width * height
    if count == pixels:
        return False
    if count < pixels * 0.05:
        return False
    rows = cv2.reduce(neutral, 1, cv2.REDUCE_SUM, dtype=cv2.CV_32S)
    if int(rows.max()) >= round(width * 255 * 0.95):
        return True
    return cv2.countNonZero(neutral[-16:]) >= round(width * 16 * 0.8)


def decode_jpeg(data):
    if not data or len(data) < 4:
        return None
    if data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        return None
    try:
        import cv2
        import numpy as np

        encoded = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None or _has_decoder_fill(image):
            return None
        return image
    except Exception:
        return None


def is_valid_jpeg(data):
    return decode_jpeg(data) is not None
