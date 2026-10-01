#!/usr/bin/env python3
import os
import sys


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "source-repo"
    output = sys.argv[2] if len(sys.argv) > 2 else "source-conventions.md"
    
    content = []

    if os.path.isfile(f"{base}/README.md"):
        with open(f"{base}/README.md") as f:
            content.append("## Project README")
            content.append("```")
            for i, line in enumerate(f):
                if i >= 100:
                    break
                content.append(line.rstrip())
            content.append("```")

    patterns = [
        ("docs/ARCHITECTURE.md", "Architecture", 100),
        ("ARCHITECTURE.md", "Architecture", 100),
        ("docs/DESIGN_PRINCIPLES.md", "Design Principles", 100),
        ("DESIGN_PRINCIPLES.md", "Design Principles", 100),
        ("docs/CODE_STYLE.md", "Code Style", 50),
        ("CODE_STYLE.md", "Code Style", 50),
        ("CONTRIBUTING.md", "Contributing", 50),
        (".github/CONTRIBUTING.md", "Contributing", 50),
        ("CLAUDE.md", "AI Rules", 100),
        (".cursorrules", "AI Rules", 100),
        (".github/copilot-instructions.md", "AI Rules", 100),
        ("package.json", "Package Metadata", 200),
        ("requirements.txt", "Python Deps", 200),
    ]

    seen = set()
    for pattern, title, max_lines in patterns:
        path = f"{base}/{pattern}"
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        with open(path) as f:
            content.append(f"## {title} ({pattern})")
            content.append("```")
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                content.append(line.rstrip())
            content.append("```")

    output_text = "\n\n".join(content)
    with open(output, "w") as f:
        f.write(output_text)

    print(f"Conventions written to {output} ({len(content)} sections)")

    out_file = os.environ.get("GITHUB_OUTPUT", "")
    if out_file:
        with open(out_file, "a") as f:
            f.write(f"has_conventions={'true' if content else 'false'}\n")


if __name__ == "__main__":
    main()
