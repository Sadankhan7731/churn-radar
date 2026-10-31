"""
Update the text of the already-executed notebook with phase2_additions.py, keeping every computed output
(re-executing would re-run five paid LLM evaluations). build_notebook.py contains the same text for a full rebuild.
    .venv/bin/python src/patch_notebook.py && .venv/bin/jupyter nbconvert --to html Churn_Radar_Notebook.ipynb
"""
import nbformat as nbf

import phase2_additions as A

NB = "Churn_Radar_Notebook.ipynb"
nb = nbf.read(NB, as_version=4)
cells = nb.cells
src = lambda c: c.source if isinstance(c.source, str) else "".join(c.source)

done = set()
for i, c in enumerate(cells):
    if c.cell_type != "markdown":
        continue
    s = src(c)
    if "| 7 | Honesty section |" in s:
        s = s.replace("| 7 | Honesty section | What it gets wrong, what I would not ship, what it costs |", A.OUTLINE_ROWS)
        done.add("outline")
    if "| 12 | **The trap test" in s and "| 13 |" not in s:
        a = s.index("| 12 | **The trap test"); b = s.index("\n", a)
        s = s[:b] + "\n" + A.DEVLOG_ROWS + s[b:]
        done.add("devlog")
    if s.lstrip().startswith("## 7. Honesty section"):
        s = s.replace("## 7. Honesty section", "## 8. Honesty section", 1)
        s = s.replace("\n### What I would not yet put in front of a customer", "\n" + A.HONESTY_WRONG + "\n\n### What I would not yet put in front of a customer", 1)
        s = s.replace("\n### What it cost to run", "\n" + A.HONESTY_NOT_SHIP + "\n\n### What it cost to run", 1)
        s = s.rstrip() + "\n" + A.HONESTY_COST + "\n" + A.video_note(A.VIDEO_CHAT_MODEL) + "\n"
        honesty_at = i
        done.add("honesty")
    c.source = s
assert done == {"outline", "devlog", "honesty"}, f"notebook already patched or changed: {done}"
cells.insert(honesty_at, nbf.v4.new_markdown_cell(A.SECTION_7))
nbf.write(nb, NB)
print("patched:", sorted(done), "+ section 7")
