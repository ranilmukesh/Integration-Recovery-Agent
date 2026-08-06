import os

def export_app_codebase(app_dir: str, output_file: str):
    app_dir = os.path.abspath(app_dir)
    py_files = sorted([
        f for f in os.listdir(app_dir)
        if f.endswith(".py") and os.path.isfile(os.path.join(app_dir, f))
    ])

    md_lines = [
        "# App Codebase Export",
        "",
        f"Exported `{len(py_files)}` Python files from `{app_dir}`.",
        ""
    ]

    for filename in py_files:
        file_path = os.path.join(app_dir, filename)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        md_lines.append(f"## `app/{filename}`")
        md_lines.append("")
        md_lines.append("```python")
        md_lines.append(content.rstrip())
        md_lines.append("```")
        md_lines.append("")

    export_content = "\n".join(md_lines)

    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(export_content)

    print(f"Successfully exported {len(py_files)} files to: {output_file}")


if __name__ == "__main__":
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    target_app_dir = os.path.join(base_dir, "app")
    target_output_file = os.path.join(base_dir, "app_codebase_export.md")
    
    export_app_codebase(target_app_dir, target_output_file)
