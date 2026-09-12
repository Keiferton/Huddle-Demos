"""Install the Huddle export entry into the current user's Inkscape extensions."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
profile = Path(os.environ.get("INKSCAPE_PROFILE_DIR", Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "inkscape"))
extensions = profile / "extensions"
if not (ROOT / ".tools/gcodeplot/gcodeplot.py").is_file():
    raise SystemExit("Install .tools/gcodeplot first; see README")
launcher = "# Huddle-Demos Inkscape exporter\nimport runpy\nrunpy.run_path(" + repr(str(ROOT / "plotter/convert.py")) + ", run_name='__main__')\n"
files = {
    "huddle_plotter.py": launcher,
    "huddle_plotter.inx": (Path(__file__).parent / "huddle_plotter.inx").read_text(),
}
# Refuse to replace an unrelated extension using the same filename.
for name in files:
    target = extensions / name
    if target.exists() and "Huddle" not in target.read_text():
        raise SystemExit(f"Refusing to replace unrelated file: {target}")
extensions.mkdir(parents=True, exist_ok=True)
for name, content in files.items():
    (extensions / name).write_text(content)
print(f"Installed Huddle pen plotter in {extensions}. Restart Inkscape.")
