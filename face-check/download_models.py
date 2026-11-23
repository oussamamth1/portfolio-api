"""Download the detection + recognition ONNX files of InsightFace model packs into $MODEL_ROOT."""
import io
import os
import sys
import urllib.request
import zipfile

FILES = {
    "buffalo_s": ("det_500m.onnx", "w600k_mbf.onnx"),
    "buffalo_l": ("det_10g.onnx", "w600k_r50.onnx"),
}
URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/{}.zip"
root = os.environ.get("MODEL_ROOT", "/models")

for name in sys.argv[1:]:
    out = os.path.join(root, name)
    os.makedirs(out, exist_ok=True)
    print(f"downloading {name}...", flush=True)
    data = urllib.request.urlopen(URL.format(name), timeout=300).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            base = os.path.basename(member)
            if base in FILES[name]:
                with open(os.path.join(out, base), "wb") as f:
                    f.write(z.read(member))
                print("  ", base, flush=True)
    missing = [f for f in FILES[name] if not os.path.exists(os.path.join(out, f))]
    if missing:
        sys.exit(f"missing files for {name}: {missing}")
