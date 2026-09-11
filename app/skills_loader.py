from pathlib import Path

import frontmatter
from langchain_core.tools import tool


def scan_skills(skills_dir):
    root = Path(skills_dir).resolve()
    result = []
    names = set()
    for md in sorted(root.glob('*/SKILL.md')):
        if not md.resolve().is_relative_to(root):
            raise ValueError('Skill symlink escapes skills directory')
        post = frontmatter.load(md)
        name, description = post.get('name'), post.get('description')
        if not isinstance(name, str) or not isinstance(description, str) or not name or not description:
            raise ValueError(f'Invalid skill metadata: {md.name}')
        if name in names:
            raise ValueError(f'Duplicate skill: {name}')
        names.add(name)
        result.append({'name': name, 'description': description, 'path': str(md)})
    return sorted(result, key=lambda m: m['name'])


def load_skill_body(name, skills_dir):
    for meta in scan_skills(skills_dir):
        if meta['name'] != name:
            continue
        md = Path(meta['path'])
        body = md.read_text(encoding='utf-8')
        for ref in sorted((md.parent / 'reference').rglob('*')):
            if not ref.resolve().is_relative_to(md.parent.resolve()):
                raise ValueError('Reference escapes skill directory')
            if ref.is_file() and ref.suffix in {'.py', '.md'}:
                body += f'\n\n## Reference: {ref.relative_to(md.parent)}\n```\n{ref.read_text(encoding="utf-8")}\n```'
        return body
    raise ValueError(f'Unknown skill: {name}')


def make_skill_tools(skills_dir, loaded=None):
    loaded = loaded if loaded is not None else set()

    @tool
    def list_skills() -> list[dict]:
        """List the names and descriptions of available analysis skills."""
        return [{k: m[k] for k in ('name', 'description')} for m in scan_skills(skills_dir)]

    @tool
    def read_skill(name: str) -> str:
        """Load a skill's complete methodology and reference scripts before analysis."""
        body = load_skill_body(name, skills_dir)
        loaded.add(name)
        return body

    lines = [f"- {m['name']}: {m['description']}" for m in scan_skills(skills_dir)]
    return [list_skills, read_skill], lines
