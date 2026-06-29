import os
import re
import shutil

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    skills_dir = os.path.join(root_dir, 'ai-hub', 'skills')
    
    # Target directories
    claude_dir = os.path.join(root_dir, '.claude', 'commands')
    cursor_dir = os.path.join(root_dir, '.cursor', 'rules')
    qoder_dir = os.path.join(root_dir, '.qoder', 'skills')

    if not os.path.exists(claude_dir):
        os.makedirs(claude_dir)
    if not os.path.exists(cursor_dir):
        os.makedirs(cursor_dir)
    if not os.path.exists(qoder_dir):
        os.makedirs(qoder_dir)

    # Clean existing Claude skills
    for file in os.listdir(claude_dir):
        file_path = os.path.join(claude_dir, file)
        if os.path.islink(file_path) or os.path.isfile(file_path):
            os.remove(file_path)

    # Clean existing Cursor skills (only those prefixed with 'skill-')
    for file in os.listdir(cursor_dir):
        if file.startswith('skill-') and file.endswith('.mdc'):
            file_path = os.path.join(cursor_dir, file)
            if os.path.islink(file_path) or os.path.isfile(file_path):
                os.remove(file_path)

    # Clean existing Qoder skills (remove subdirectories containing SKILL.md)
    for entry in os.listdir(qoder_dir):
        entry_path = os.path.join(qoder_dir, entry)
        if os.path.isdir(entry_path):
            skill_md = os.path.join(entry_path, 'SKILL.md')
            if os.path.exists(skill_md):
                shutil.rmtree(entry_path)

    for skill_folder in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, skill_folder)
        skill_md_path = os.path.join(skill_path, 'SKILL.md')

        if os.path.isdir(skill_path) and os.path.exists(skill_md_path):
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find name in frontmatter
            match = re.search(r'^name:\s*([^\s]+)', content, re.MULTILINE)
            if match:
                skill_name = match.group(1).strip('"\'')
                
                # Setup Claude destination
                claude_dest = os.path.join(claude_dir, f"{skill_name}.md")

                # Setup Cursor destination (prefix with 'skill-' to avoid messing with core rules)
                cursor_dest = os.path.join(cursor_dir, f"skill-{skill_name}.mdc")

                # Setup Qoder destination (directory per skill)
                qoder_skill_dir = os.path.join(qoder_dir, skill_name)
                qoder_dest = os.path.join(qoder_skill_dir, 'SKILL.md')

                try:
                    # Sync Claude
                    shutil.copy2(skill_md_path, claude_dest)
                    # Sync Cursor
                    shutil.copy2(skill_md_path, cursor_dest)
                    # Sync Qoder (needs its own directory)
                    os.makedirs(qoder_skill_dir, exist_ok=True)
                    shutil.copy2(skill_md_path, qoder_dest)
                    print(f"Synced: /{skill_name} -> Claude, Cursor & Qoder")
                except Exception as e:
                    print(f"Failed to sync {skill_name}: {e}")

if __name__ == "__main__":
    main()
