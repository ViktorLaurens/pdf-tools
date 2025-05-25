import pdfplumber

labels = {}
with pdfplumber.open("input.pdf") as doc:
    for page in doc.pages:
        text_objs = page.extract_words()
        for f in fields:
            x0, y0, x1, y1 = map(float, f.get("/Rect"))
            # find the nearest word just above the field:
            candidates = [
                w for w in text_objs
                if w["x1"] < x1 and abs(w["bottom"] - y1) < 20
            ]
            if candidates:
                # pick the rightmost (closest) word
                label = sorted(candidates, key=lambda w: w["x1"], reverse=True)[0]["text"]
                labels[f.get("/T")] = label
